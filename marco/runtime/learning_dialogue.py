"""Durable dialogue session: ReasoningContext over a user-taught LearningMemory.

The context answers every turn; memory only supplies explicitly taught expressions.
Every committed observation slot owns its archived reading in the context's reading ledger, so
teach/retract never reinterprets history, even when a later turn forces a full replay.  New
utterances, including identical wording, are read by the installed ordinary parser.
"""
import copy
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager

import pack_model
from marco.learning.memory import LearningMemory
from marco.reasoning.context import ReasoningContext
from marco.storage.overlay import dumps
from marco.language.teaching import read_learning_control

from marco.reasoning.readings import ReadingUnavailable, make_record
from marco.runtime.dialogue_trace import DialogueTrace
from marco.runtime.selected_graph import prepare_selected_graph, judge_selected_graph
from language_components import decode_language_pack, validate_native_judge_routes, read_native_judge_route

NATIVE_HISTORY_LIMIT = 64
_NATIVE_RESULT_KEYS = {"verdict", "reply", "status", "gap", "provenance", "trace"}

SCHEMA_V1 = "marco2-dialogue-session-v1"
SCHEMA = "marco2-dialogue-session-v2"
CONTEXT_SCHEMA = "reasoning-context-v11"
EVIDENCE_KEYS = {"evidence", "증거"}


class SessionPersistenceError(OSError):
    """Memory committed, but the session file could not be saved; reopen before continuing."""


def _text(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)
    return value


def _nonneg(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _json(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _native_identity_equal(reported, expected):
    """Exact-type identity for reported finite metadata (bool/int/float never substitute).

    Recurses through dicts and lists; strings and None must match exactly."""
    if type(reported) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(reported) == set(expected) and all(
            _native_identity_equal(reported[k], expected[k]) for k in expected)
    if isinstance(expected, list):
        return len(reported) == len(expected) and all(
            _native_identity_equal(a, b) for a, b in zip(reported, expected))
    if isinstance(expected, float):
        return expected == expected and reported == expected \
            and expected not in (float("inf"), float("-inf"))
    return reported == expected


def _strip_evidence(value):
    if isinstance(value, dict):
        return {k: _strip_evidence(v) for k, v in value.items() if k not in EVIDENCE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_strip_evidence(v) for v in value]
    return value


class DialogueSession:
    def __init__(self, memory_path, state_path=None, *, language="english", conversation_id=None,
                 max_turns=128, effort=3, research_hook=None, model=None, trace_ledger=None,
                 learning_controls=False, graph_assets=None, graph_member_path=None):
        if (graph_assets is None) != (graph_member_path is None):
            raise ValueError("graph_assets and graph_member_path must be given together")
        self._selected, self._native_turns, self._native_history_gap = None, [], None
        self._graph_assets, self._graph_member, self._native_pack, self._language_witness = None, None, None, None
        if type(learning_controls) is not bool:
            raise ValueError("learning_controls must be a bool")
        if learning_controls and type(model) is not pack_model.PackModel:
            raise ValueError("learning_controls requires an explicit selected PackModel")
        self._learning_enabled = learning_controls
        self._learning = {"targets": {}, "draft": None}     # ephemeral; never serialized
        self._learning_gap = None       # passive finite collection-gap metadata (None = no gap)
        if conversation_id is not None:
            _text("conversation_id", conversation_id)
        if research_hook is not None and not callable(research_hook):
            raise ValueError("research_hook must be callable")
        if trace_ledger is not None and getattr(trace_ledger, "fsync", None) is not True:
            raise ValueError("trace_ledger must be an fsync-enabled Ledger")
        self.trace_ledger, self._recorder, self._active, self.last_trace = trace_ledger, None, None, None
        self.language, self.effort, self.max_turns = language, effort, max_turns
        self.research_hook = research_hook
        self.state_path = os.fspath(state_path) if state_path is not None else None
        self.memory, self._closed, self._persistence_failed = None, False, False
        self._parser_revision = 0
        self.turn_counter = 0
        self._checkpoint = None
        if graph_assets is not None and type(model) is not pack_model.PackModel:
            # explicit graph opt-in is validated before any development model, parser or Memory
            raise ValueError("selected graph requires an explicit PackModel")
        if model is None:
            # development convenience only: a selected model is always passed explicitly
            model = pack_model.development_model(language)
        else:
            self.language = (model.declaration or {}).get("language") or language
        self.model = model
        seed = model.parser()
        self.base_sha256 = hashlib.sha256(dumps({"data": seed.data, "language_pack": seed.language_pack})
                                          .encode("utf-8")).hexdigest()
        self._knowledge_binding = model.content_fingerprint
        if graph_assets is not None:
            self._prepare_native(model, graph_assets, graph_member_path)
        # an unbound (pre-graph-binding) store is rejected here, never upgraded or mutated
        self.memory = LearningMemory(memory_path, seed, graph_binding=self._knowledge_binding)
        try:
            self.context = ReasoningContext(model=model, max_turns=max_turns, effort=effort)
            self.conversation_id = conversation_id or "conv_" + uuid.uuid4().hex
            self.context.conversation_id = self.conversation_id
            if trace_ledger is not None:
                self.context.trace = trace_ledger     # engine pending events; the caller owns the ledger
            if self.state_path and os.path.exists(self.state_path):
                self._load(conversation_id)
            else:
                self._rehydrate(self.context.snapshot())
                self.save()
            if trace_ledger is not None:
                # bound to the conversation actually restored, not the requested id
                self._recorder = DialogueTrace(trace_ledger, conversation=self.conversation_id,
                                               runtime_stamp=self._trace_stamp(), provenance={})
        except BaseException:
            self.memory.close()
            self._closed = True
            raise

    # --- lifecycle -------------------------------------------------------------------

    def close(self):
        if not self._closed:
            self._closed = True
            self.memory.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def _guard(self):
        if self._closed:
            raise RuntimeError("session is closed")
        if self._persistence_failed:
            raise SessionPersistenceError("Reopen the session after the failed state save.")
        yield

    # --- public API ------------------------------------------------------------------

    def respond(self, text):
        _text("text", text)
        if self._recorder is None:
            return self._respond(text)
        return self._traced(text, lambda: self._respond(text), "respond")

    def _prepare_native(self, model, graph_assets, member_path):
        if type(model) is not pack_model.PackModel:
            raise ValueError("selected graph requires an explicit PackModel")
        if not isinstance(graph_assets, dict):
            raise ValueError("graph_assets must be a dict")
        table = dict(graph_assets)
        prepared = prepare_selected_graph(model, table, member_path)
        language_member = (model.declaration or {}).get("language")
        raw = table.get(language_member)
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError("bound raw language member is unavailable")
        raw = bytes(raw)
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("bound raw language member is not finite JSON") from exc
        if not isinstance(loaded, dict):
            raise ValueError("bound raw language member must be an object")
        pack = decode_language_pack(loaded, language_member)
        validate_native_judge_routes(pack)
        if not model.permits("engine.judge"):
            raise ValueError("selected model does not permit engine.judge")
        preimage = {"model_content_fingerprint": prepared.model_content_fingerprint,
                    "graph_member_path": prepared.member_path, "graph_member_sha256": prepared.member_sha256}
        self._knowledge_binding = hashlib.sha256(json.dumps(
            preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")).hexdigest()
        self._selected, self._graph_assets, self._graph_member, self._native_pack = prepared, table, member_path, pack
        self._language_witness = {"language_member_path": language_member,
                                  "language_member_sha256": hashlib.sha256(raw).hexdigest()}

    def _native_history_valid(self, entries, counter):
        """Strictly validate the reported native history carrier (finite JSON shape only).

        Nothing historical is reparsed or rejudged; template declarations are checked against the
        currently bound declaration list and the actual selected Prepared graph fields."""
        from language_components import _native_judge_items
        bad = ValueError("native history invalid")
        if not isinstance(entries, list) or len(entries) > NATIVE_HISTORY_LIMIT:
            raise bad
        if type(counter) is not int or counter < 0:
            raise bad
        sint = lambda v: type(v) is int
        sha_ok = lambda v: isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)
        declared = {index: (item, slot, prefix, suffix)
                    for index, item, slot, prefix, suffix in _native_judge_items(self._native_pack)}
        prepared = self._selected
        expected_binding = {"model_content_fingerprint": prepared.model_content_fingerprint,
                            "graph_member_path": prepared.member_path,
                            "graph_member_sha256": prepared.member_sha256,
                            "reference_encoder_declaration": getattr(prepared, "reference_encoder_declaration", None)}
        last = 0
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"turn", "source", "source_sha256", "route", "native_result"}:
                raise bad
            turn, source, route, result = entry["turn"], entry["source"], entry["route"], entry["native_result"]
            if not sint(turn) or turn < 1 or turn <= last or turn > counter:
                raise bad
            last = turn
            if not isinstance(source, str) or not source or not sha_ok(entry["source_sha256"]) \
                    or entry["source_sha256"] != hashlib.sha256(source.encode("utf-8")).hexdigest():
                raise bad
            if not isinstance(route, dict):
                raise bad
            if route.get("status") == "held":
                if route != {"status": "held", "gap": "native_route_ambiguous"} or result is not None:
                    raise bad
            else:
                if set(route) != {"status", "operator", "input_slot", "text", "span",
                                  "template_index", "template_sha256"}:
                    raise bad
                slot, capture, span, index = route["input_slot"], route["text"], route["span"], route["template_index"]
                if route["status"] != "matched" or route["operator"] != "engine.judge":
                    raise bad
                if not isinstance(slot, str) or not slot.strip() or slot != slot.strip() \
                        or "{" in slot or "}" in slot:
                    raise bad
                if not isinstance(capture, str) or not capture or capture != capture.strip():
                    raise bad
                if not isinstance(span, dict) or set(span) != {"start", "end", "text"} \
                        or not sint(span["start"]) or not sint(span["end"]) \
                        or not (0 <= span["start"] < span["end"] <= len(source)) \
                        or source[span["start"]:span["end"]] != capture or span["text"] != capture:
                    raise bad
                if not sint(index) or index < 0 or index not in declared:
                    raise bad
                item, declared_slot, prefix, suffix = declared[index]
                if declared_slot != slot or item.get("result", {}).get("operator") != "engine.judge":
                    raise bad
                # Literal wrapper congruence (data/span only; no reparse): the reported source must
                # carry this declaration's actual prefix/suffix with the capture as the stripped body.
                if not isinstance(prefix, str) or not isinstance(suffix, str):
                    raise bad
                if len(source) < len(prefix) + len(suffix) + len(capture) \
                        or not source.startswith(prefix) or not source.endswith(suffix):
                    raise bad
                body = source[len(prefix):len(source) - len(suffix)]
                if not body or body.strip() != capture:
                    raise bad
                if span["start"] != len(prefix) + (len(body) - len(body.lstrip())) \
                        or span["end"] != span["start"] + len(capture):
                    raise bad
                digest = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":"),
                                                   ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
                if route["template_sha256"] != digest:
                    raise bad
                if not isinstance(result, dict) or set(result) != _NATIVE_RESULT_KEYS or result["trace"] is not None:
                    raise bad
                if not isinstance(result["verdict"], str) or not (result["reply"] is None or isinstance(result["reply"], str)):
                    raise bad
                status, gap = result["status"], result["gap"]
                if status not in ("answered", "held") or not (gap is None or isinstance(gap, str)):
                    raise bad
                if (status == "answered" and gap is not None) or (status == "held" and not gap):
                    raise bad
                # Native engine ABI: status 'answered' iff verdict is the protocol tag '인정'.
                if (status == "answered") != (result["verdict"] == "인정"):
                    raise bad
                prov = result["provenance"]
                if not isinstance(prov, dict) or set(prov) != {
                        "model_content_fingerprint", "graph_member_path", "graph_member_sha256",
                        "reference_encoder_declaration", "candidates", "proof_status",
                        "used_edge_path", "used_learning", "used_readings", "used_rule"}:
                    raise bad
                for key, value in expected_binding.items():
                    if not _native_identity_equal(prov[key], value):
                        raise bad
                if prov["proof_status"] != "partial" or any(
                        prov[k] is not None for k in ("used_edge_path", "used_learning", "used_readings", "used_rule")):
                    raise bad
                cands = prov["candidates"]
                if not isinstance(cands, dict) or set(cands) != {"evidence", "claim", "native_confidence"}:
                    raise bad
                if not all(cands[k] is None or isinstance(cands[k], str) for k in ("evidence", "claim")):
                    raise bad
                conf = cands["native_confidence"]
                if conf is not None and (type(conf) is not float or conf != conf or conf in (float("inf"), float("-inf"))):
                    raise bad
            json.dumps(entry, allow_nan=False)
        return _json(entries)

    def _native_result(self, text, route):
        if route["status"] == "held":
            judged = None
            self._native_witness(text, route, None)
            out = {"answer": None, "status": "unresolved", "operator": None,
                   "meaning": {"act": "hold", "gap": route["gap"]}, "transitions": [],
                   "verification": {"status": "unknown", "checks": []},
                   "native_verdict": None, "native_gap": route["gap"], "native_provenance": None}
            return out, judged
        self._native_witness(text, route, None)
        judged = judge_selected_graph(self.model, self._graph_assets, self._graph_member, route["text"],
                                      trace_ledger=None, conversation_id=None)
        answered = judged.get("status") == "answered"
        meaning = ({"act": "native_judgement", "verdict": judged.get("verdict")} if answered
                   else {"act": "hold", "gap": judged.get("gap"), "verdict": judged.get("verdict")})
        out = {"answer": judged.get("reply"), "status": "answered" if answered else "unresolved",
               "operator": "engine.judge", "meaning": meaning, "transitions": [],
               "verification": {"status": "unknown", "checks": []},
               "native_verdict": judged.get("verdict"), "native_gap": judged.get("gap"),
               "native_provenance": judged.get("provenance")}
        return out, judged

    def _native_record(self, text, route, judged, out):
        """Append the reported history entry; capacity or detach failure keeps the prior carrier."""
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            # optional reported metadata: detach inside this local boundary; the actual native
            # result is already computed and is never rolled back by a metadata failure
            self._native_witness(text, route, out.get("meaning"))
            if self._active is not None:
                self._active["selected_native_judgement"] = _json(out.get("native_provenance"))
            if len(self._native_turns) >= NATIVE_HISTORY_LIMIT:
                raise ValueError("native history capacity")
            entry = _json({"turn": self.turn_counter, "source": text, "source_sha256": source_sha,
                           "route": route, "native_result": judged})
            self._native_turns = self._native_turns + [entry]
        except Exception:
            self._native_history_gap = {"code": "native_history_unavailable"}

    def _native_witness(self, text, route, reading):
        """Mark the actual native attempt on the active trace before/after judge; never raises past
        the active marker, so stale typed Context.flush_trace is skipped even on judge exception."""
        if self._active is None:
            return
        self._active.setdefault("selected_native_judgement", None)
        self._active["selected_native_route"] = {"native_attempt": True}
        try:
            self._active["selected_native_route"] = _json(dict(
                self._language_witness, source=text,
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                route=route, reading=reading))
        except Exception:
            self._active["selected_native_route"] = {"native_attempt": True,
                                                     "gap": {"code": "native_route_witness_unavailable"}}

    def _answer_query_learning_dependencies(self, text, result, out):
        import hashlib, json, copy
        INPUT_KEYS = ("input_id", "text_sha256", "conversation_id", "model_binding", "parser_base_sha256",
                      "parser_grammar_sha256", "memory_head_before", "memory_head_after", "installed_memory_head")
        MODEL_KEYS = ("content_fingerprint", "effective_key", "knowledge_binding", "graph_member_sha256")
        VALUE_KEYS = {"text_sha256", "parser_base_sha256", "parser_grammar_sha256", "installed_memory_head",
                      "query", "entry_selection"}
        CARRIER_KEYS = {"source", "calls", "parser", "value", "gap"}
        inp = dict.fromkeys(INPUT_KEYS)
        inp["model_binding"] = dict.fromkeys(MODEL_KEYS)
        items, gaps = [], []

        def gap(code, clause=0):
            return {"query_ordinal": 0, "clause_ordinal": clause, "code": code}

        def strict(number):
            return isinstance(number, int) and not isinstance(number, bool)

        def nonblank(value):
            return isinstance(value, str) and value.strip() != ""

        def head_shape(head):
            # native OverlayStore.head(): (0, None) for an empty overlay, else positive seq + change id
            return (isinstance(head, dict) and set(head) == {"seq", "change_id"}
                    and strict(head["seq"]) and head["seq"] >= 0
                    and (head["change_id"] is None if head["seq"] == 0 else nonblank(head["change_id"])))

        def hex64(value):
            return (isinstance(value, str) and len(value) == 64
                    and all(c in "0123456789abcdef" for c in value))

        def controlled(code):
            # a bounded diagnostic token only; never arbitrary text/path/error detail
            return (nonblank(code) and len(code) <= 64 and code.replace("_", "").isalnum()
                    and code.isascii()
                    and code in ("acceptance_mismatch", "acceptance_unavailable", "answer_unsupported",
                                 "binding_unknown", "capsule_invalid", "capture_failed", "catalog_unmatched",
                                 "collection_failed", "condition_scope_uncollected",
                                 "current_read_carrier_invalid", "current_read_missing", "current_read_nested",
                                 "current_read_source_mismatch", "current_read_unavailable",
                                 "derivation_unavailable", "filler_source_offset_unproven",
                                 "grammar_cache_unavailable", "input_mismatch", "native_alignment_unproven",
                                 "native_gap_invalid", "native_item_invalid", "native_item_unavailable",
                                 "native_selection_invalid", "native_selection_overflow",
                                 "native_selection_unavailable", "origin_alignment_invalid",
                                 "origin_index_unavailable", "origin_invalid", "origin_mismatch",
                                 "origin_unavailable", "origin_unknown", "owner_unavailable", "query_mismatch",
                                 "query_unsupported", "recorder_unavailable", "relative_source_offset_unproven",
                                 "stale_binding", "stale_head", "uncollected_index", "uncollected_scope",
                                 "unsupported_query", "value_overflow"))

        def plain_query(query):
            # one current plain binary query: exactly triple/render, one asked endpoint, grounded endpoint,
            # literal relation (mirrors the native query reference contract; no parsing, no lexicon)
            if not isinstance(query, list) or len(query) != 1 or not isinstance(query[0], dict):
                return None
            record = query[0]
            if set(record) != {"triple", "render"}:
                return None
            triple, render = record["triple"], record["render"]
            if (not isinstance(triple, list) or len(triple) != 3
                    or any(not isinstance(x, str) or not x for x in triple)
                    or not isinstance(render, list) or not render
                    or any(not isinstance(x, str) for x in render)
                    or triple[1].startswith(("$", "?"))):
                return None
            asked = [i for i in (0, 2) if triple[i].startswith("?")]
            if len(asked) != 1 or len(triple[asked[0]]) < 2 or triple[2 - asked[0]].startswith(("$", "?")):
                return None
            return triple, render, asked[0]

        def collect():
            carrier = self.context.__dict__.pop("_current_query_read", None)
            if not isinstance(carrier, dict) or set(carrier) != CARRIER_KEYS:
                return "current_read_missing"
            calls = carrier["calls"]
            if not strict(calls) or calls < 1:
                return "current_read_missing"
            if calls > 1:
                return "current_read_nested"
            carrier_gap = carrier["gap"]
            if carrier_gap is not None and not controlled(carrier_gap):
                carrier_gap = "current_read_unavailable"
            value, parser = carrier["value"], carrier["parser"]
            if not isinstance(value, dict) or set(value) != VALUE_KEYS or parser is None:
                # absent/malformed value: one controlled local gap, nothing to transport
                return carrier_gap if carrier_gap is not None else "current_read_unavailable"
            # genuine current respond owner, its actual Attempt and the installed recorder/ledger
            active = self._active
            if not isinstance(active, dict) or active.get("trace_kind") != "respond":
                return "owner_unavailable"
            attempt, recorder = active.get("trace_attempt"), active.get("trace_recorder")
            if (recorder is None or recorder is not self._recorder or attempt is None
                    or getattr(recorder, "ledger", None) is None
                    or self.trace_ledger is None or recorder.ledger is not self.trace_ledger
                    or getattr(recorder.ledger, "fsync", None) is not True
                    or getattr(recorder, "conversation", None) != self.conversation_id):
                return "recorder_unavailable"
            try:
                recorder._open(attempt)
            except Exception:
                return "recorder_unavailable"
            if (attempt.text != text or attempt.conversation != self.conversation_id
                    or hashlib.sha256(attempt.text.encode("utf-8")).hexdigest() != inp["text_sha256"]
                    or not nonblank(attempt.input_id) or inp["input_id"] != attempt.input_id):
                return "input_mismatch"
            # Attempt model stamp bound to the actual Session model; foreign/null stamps admit nothing
            stamp = attempt.runtime_stamp
            expected_model = {"content_fingerprint": self.model.content_fingerprint,
                              "effective_key": self.model.effective_key}
            if (not isinstance(stamp, dict) or not nonblank(expected_model["content_fingerprint"])
                    or not nonblank(expected_model["effective_key"])
                    or not _native_identity_equal(stamp.get("model"), expected_model)
                    or not _native_identity_equal(inp["model_binding"]["content_fingerprint"],
                                                  expected_model["content_fingerprint"])
                    or not _native_identity_equal(inp["model_binding"]["effective_key"],
                                                  expected_model["effective_key"])):
                return "stale_binding"
            # exact actual Memory heads before/after, unchanged, equal to the installed revision
            before = inp["memory_head_before"]
            after = inp["memory_head_after"]
            seq = after["seq"] if head_shape(after) else None
            if (not head_shape(before) or not head_shape(after) or not _native_identity_equal(before, after)
                    or not _native_identity_equal(attempt.provenance.get("installed_memory_head"), before)
                    or not _native_identity_equal(value["installed_memory_head"], seq)
                    or not _native_identity_equal(self._parser_revision, seq)
                    or not _native_identity_equal(self._revision(), seq)
                    or not _native_identity_equal(inp["installed_memory_head"], seq)):
                return "stale_head"
            # installed parser identity, base and installed grammar hashes (installed cache, no reparse)
            cache = self.context._grammar_cache
            if (self.context._parser_instance is not parser
                    or not isinstance(cache, tuple) or len(cache) != 2 or cache[0] is not parser
                    or not nonblank(cache[1]) or not nonblank(self.base_sha256)
                    or not _native_identity_equal(value["text_sha256"], inp["text_sha256"])
                    or not _native_identity_equal(value["parser_base_sha256"], self.base_sha256)
                    or not _native_identity_equal(inp["parser_base_sha256"], self.base_sha256)
                    or not _native_identity_equal(value["parser_grammar_sha256"], cache[1])
                    or not _native_identity_equal(inp["parser_grammar_sha256"], cache[1])):
                return "stale_binding"
            # raw and delivered plain answered/inform meaning without advanced/conditional metadata
            for payload in (result, out):
                if (not isinstance(payload, dict) or payload.get("status") != "answered"
                        or not isinstance(payload.get("meaning"), dict)
                        or payload["meaning"].get("act") != "inform"
                        or payload["meaning"].get("kind") is not None
                        or any(payload.get(key) is not None
                               for key in ("kind", "relation_attempt", "conditional", "condition", "assumption"))):
                    return "answer_unsupported"
            parsed = plain_query(value["query"])
            if parsed is None:
                return "query_unsupported"
            triple, render, asked_index = parsed
            for payload in (result, out):
                meaning = payload["meaning"]
                asked = meaning.get("asked")
                # the whole original question triple (Context meaning.asked), query and render agree exactly
                if (not _native_identity_equal(meaning.get("query"), triple)
                        or not _native_identity_equal(meaning.get("render"), render)
                        or not _native_identity_equal(asked, triple)):
                    return "query_mismatch"
            selection = value["entry_selection"]
            if (not isinstance(selection, dict)
                    or set(selection) != {"schema", "scope", "status", "coordinate_space", "items", "gaps"}
                    or selection["schema"] != "marco-entry-selection-v1"
                    or selection["scope"] != "known_selected_input_clauses"
                    or selection["status"] != "partial"
                    or selection["coordinate_space"] != "parser_view"
                    or not isinstance(selection["items"], list) or not isinstance(selection["gaps"], list)):
                return "native_selection_invalid"
            native = []
            for entry in selection["gaps"]:
                if (isinstance(entry, dict) and set(entry) == {"clause_ordinal", "code"}
                        and controlled(entry["code"])
                        and (entry["clause_ordinal"] is None
                             or strict(entry["clause_ordinal"]) and entry["clause_ordinal"] >= 0)):
                    native.append(gap(entry["code"], entry["clause_ordinal"]))
                else:
                    native.append(gap("native_gap_invalid", None))
            gaps.extend(native)
            if carrier_gap is not None and not native:
                # Context's controlled diagnostic travels beside the intact native gaps; no item is admitted
                gaps.append(gap(carrier_gap))
                return None
            if len(selection["items"]) != 1:
                if not native:
                    gaps.append(gap("native_item_unavailable"))
                return None
            if native:
                return None
            item = selection["items"][0]
            if (not isinstance(item, dict)
                    or set(item) != {"clause_ordinal", "span", "compiler_index", "origin", "targets", "derivation"}):
                return "native_item_invalid"
            span, index = item["span"], item["compiler_index"]
            if (not strict(item["clause_ordinal"]) or item["clause_ordinal"] != 0
                    or not isinstance(span, list) or len(span) != 2 or not all(strict(n) for n in span)
                    or not 0 <= span[0] < span[1] <= len(text) or not strict(index) or index < 0
                    or not _native_identity_equal(item["targets"], {"facts": [], "query": [0]})
                    or item["derivation"] is not None):
                return "native_item_invalid"
            origin = item["origin"]
            if origin is None:
                gaps.append(gap("origin_unknown"))
                return None
            from marco.language.entry_origins import validated_entry_origin
            # actual selected annotation: native vector row and installed example agree with the origin
            try:
                valid = validated_entry_origin(origin)
                if not isinstance(valid, dict) or not _native_identity_equal(valid, origin):
                    return "origin_invalid"
                vector, examples = getattr(parser, "_entry_origins", None), parser.data["examples"]
                if (not isinstance(vector, list) or not isinstance(examples, list)
                        or len(vector) != len(examples) or not index < len(vector)):
                    return "origin_alignment_invalid"
                if not _native_identity_equal(validated_entry_origin(vector[index]), origin):
                    return "origin_mismatch"
                example = examples[index]
                if not isinstance(example, dict):
                    return "origin_mismatch"
                if "origin" in example and not _native_identity_equal(validated_entry_origin(example["origin"]),
                                                                      origin):
                    return "origin_mismatch"
            except ValueError:
                return "origin_invalid"
            # exactly one full exact active catalog row (scope and graph binding included)
            rows = [r for r in self.memory.installed_expression_origins() if _native_identity_equal(r, origin)]
            if len(rows) != 1:
                return "catalog_unmatched"
            row = rows[0]
            # the selected origin's graph binding must be present and be this Session's current binding
            binding = self._model_binding()
            if (origin.get("graph_binding") is None or self._knowledge_binding is None
                    or not _native_identity_equal(origin.get("graph_binding"), self._knowledge_binding)
                    or (self._selected is not None
                        and not _native_identity_equal(binding.get("knowledge_binding"), self._knowledge_binding))
                    or not _native_identity_equal(inp["model_binding"]["knowledge_binding"], self._knowledge_binding)
                    or not _native_identity_equal(binding.get("content_fingerprint"),
                                                  inp["model_binding"]["content_fingerprint"])
                    or not _native_identity_equal(binding.get("effective_key"), inp["model_binding"]["effective_key"])
                    or not _native_identity_equal(binding.get("graph_member_sha256"),
                                                  inp["model_binding"]["graph_member_sha256"])):
                return "stale_binding"
            store = self.memory._store
            rid, cid, rev, cchg = row["rule_id"], row["candidate_id"], row["rule_revision"], row["accepted_change_id"]
            if not strict(rev) or rev < 1:
                return "acceptance_mismatch"
            change, cand = store.change(cchg), store.candidate(cid)
            if not isinstance(change, dict) or not isinstance(cand, dict):
                return "acceptance_unavailable"
            cseq = change.get("seq")
            if (not strict(cseq) or cseq < 1 or cseq > seq or not _native_identity_equal(change.get("change_id"), cchg)
                    or not _native_identity_equal(cand.get("change_seq"), cseq)
                    or not _native_identity_equal(cand.get("candidate_id"), cid)
                    or cand.get("status") != "approved"
                    or not isinstance(change.get("approval"), dict)
                    or not _native_identity_equal(change["approval"].get("candidate_id"), cid)):
                return "acceptance_mismatch"
            hits = [d for d in (change.get("deltas") if isinstance(change.get("deltas"), list) else [])
                    if isinstance(d, dict) and d.get("op") == "ADD_RULE" and d.get("target_kind") == "rule"
                    and _native_identity_equal(d.get("target_id"), rid) and strict(d.get("revision"))
                    and d["revision"] + 1 == rev]
            if len(hits) != 1 or not isinstance(hits[0].get("payload"), dict):
                return "acceptance_unavailable"
            body = hits[0]["payload"].get("body")
            report = body.get("report") if isinstance(body, dict) else None
            if (not isinstance(body, dict) or not isinstance(report, dict) or report.get("accepted") is not True
                    or body.get("kind") != "expression"
                    or report.get("induction_policy") != "selected-reference-query-slots-v1"
                    or "annotation" not in body or not _native_identity_equal(example, body["annotation"])):
                return "acceptance_mismatch"
            chits = [d for d in (cand.get("deltas") if isinstance(cand.get("deltas"), list) else [])
                     if isinstance(d, dict) and d.get("op") == "ADD_RULE"
                     and _native_identity_equal(d.get("target_id"), rid)]
            if (len(chits) != 1 or not isinstance(chits[0].get("payload"), dict)
                    or not _native_identity_equal(chits[0]["payload"].get("body"), body)):
                return "acceptance_mismatch"
            history = store.history(rid)
            if not isinstance(history, (list, tuple)) or not history:
                return "acceptance_unavailable"
            adds = [h for h in history if isinstance(h, dict) and h.get("op") == "ADD_RULE"
                    and h.get("target_kind") == "rule" and _native_identity_equal(h.get("target_id"), rid)
                    and strict(h.get("revision")) and h["revision"] + 1 == rev]
            if len(adds) != 1 or history[-1] is not adds[0]:
                return "acceptance_mismatch"
            added = adds[0]
            payload = added.get("payload")
            if (not _native_identity_equal(added.get("change_id"), cchg)
                    or not _native_identity_equal(added.get("seq"), cseq)
                    or not _native_identity_equal(added.get("revision"), hits[0]["revision"])
                    or not isinstance(payload, dict) or not _native_identity_equal(payload.get("body"), body)):
                return "acceptance_mismatch"
            for src in (added, change, cand):
                evidence = src.get("evidence")
                if (not isinstance(evidence, dict) or not _native_identity_equal(evidence.get("rule_id"), rid)
                        or not _native_identity_equal(evidence.get("candidate_id"), cid)
                        or evidence.get("kind") != "expression"):
                    return "acceptance_mismatch"
            for src in (added, change):
                if (not _native_identity_equal(src["evidence"].get("report"), report)
                        or not _native_identity_equal(src.get("validation"), report)):
                    return "acceptance_mismatch"
            teaching = body.get("provenance")
            if (not isinstance(teaching, dict)
                    or not _native_identity_equal({"conversation_id": teaching.get("conversation_id"),
                                                   "turn_id": teaching.get("turn_id")}, row["teaching"])):
                return "acceptance_mismatch"
            live = [r for r in store.added_rules() if isinstance(r, dict) and _native_identity_equal(r.get("id"), rid)]
            if (len(live) != 1 or not _native_identity_equal(live[0].get("revision"), rev)
                    or not _native_identity_equal(live[0].get("body"), body)
                    # complete native OverlayStore._item origin against the actual accepted change fields
                    or not isinstance(live[0].get("origin"), dict)
                    or not _native_identity_equal(live[0]["origin"], {
                        "change_id": cchg, "seq": cseq, "actor": change.get("actor"),
                        "source": change.get("source"), "approval": change.get("approval"),
                        "created_at": change.get("created_at")})):
                return "acceptance_mismatch"
            items.append({"query_ordinal": 0, "clause_ordinal": 0, "parser_span": list(span),
                          "compiler_index": index, "origin": copy.deepcopy(origin),
                          "original_source_span": None, "confirmation": "historical_acceptance_recorded"})
            return None

        try:
            inp["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            inp["conversation_id"] = self.conversation_id
            inp["model_binding"] = {"content_fingerprint": self.model.content_fingerprint,
                                    "effective_key": self.model.effective_key,
                                    "knowledge_binding": self._knowledge_binding,
                                    "graph_member_sha256": None if self._selected is None
                                    else self._selected.member_sha256}
            inp["parser_base_sha256"] = self.base_sha256
            cache = self.context._grammar_cache
            if isinstance(cache, tuple) and len(cache) == 2 and cache[0] is self.context._parser_instance:
                inp["parser_grammar_sha256"] = cache[1]
            after = self._binding()
            inp["memory_head_after"] = after
            if head_shape(after) and _native_identity_equal(self._parser_revision, after["seq"]):
                inp["installed_memory_head"] = after["seq"]
            active = self._active if isinstance(self._active, dict) else {}
            attempt = active.get("trace_attempt")
            inp["input_id"] = getattr(attempt, "input_id", None)
            provenance = getattr(attempt, "provenance", None)
            inp["memory_head_before"] = provenance.get("installed_memory_head") if isinstance(provenance, dict) else None
        except Exception:
            pass
        try:
            code = collect()
        except Exception:
            code = "collection_failed"
        if code is not None:
            items.clear()
            gaps[:] = [gap(code)]

        def bounded(capsule):
            from marco.trace.runtime import plain_json
            meta = plain_json(capsule)
            if (not isinstance(meta, dict)
                    or set(meta) != {"schema", "scope", "status", "basis", "input", "items", "gaps"}
                    or not isinstance(meta["input"], dict) or tuple(meta["input"]) != INPUT_KEYS
                    or not isinstance(meta["input"]["model_binding"], dict)
                    or tuple(meta["input"]["model_binding"]) != MODEL_KEYS
                    or not isinstance(meta["items"], list) or not isinstance(meta["gaps"], list)
                    or len(meta["gaps"]) > 64
                    or any(not isinstance(g, dict) or set(g) != {"query_ordinal", "clause_ordinal", "code"}
                           or not controlled(g["code"])
                           or not strict(g["query_ordinal"]) or g["query_ordinal"] < 0
                           or not (g["clause_ordinal"] is None
                                   or strict(g["clause_ordinal"]) and g["clause_ordinal"] >= 0)
                           for g in meta["gaps"])):
                raise ValueError("capsule_invalid")
            leaf, model = meta["input"], meta["input"]["model_binding"]
            if (any(not (leaf[k] is None or nonblank(leaf[k])) for k in ("input_id", "conversation_id"))
                    or any(not (leaf[k] is None or hex64(leaf[k]))
                           for k in ("text_sha256", "parser_base_sha256", "parser_grammar_sha256"))
                    or any(not (model[k] is None or hex64(model[k]))
                           for k in ("content_fingerprint", "knowledge_binding", "graph_member_sha256"))
                    or not (model["effective_key"] is None or nonblank(model["effective_key"]))
                    or any(not (leaf[k] is None or head_shape(leaf[k]))
                           for k in ("memory_head_before", "memory_head_after"))
                    or not (leaf["installed_memory_head"] is None
                            or strict(leaf["installed_memory_head"]) and leaf["installed_memory_head"] >= 0)
                    or any(not isinstance(i, dict) or set(i) != {"query_ordinal", "clause_ordinal", "parser_span",
                                                                 "compiler_index", "origin", "original_source_span",
                                                                 "confirmation"} for i in meta["items"])):
                raise ValueError("capsule_invalid")
            blob = json.dumps(meta, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
            if len(blob.encode("utf-8")) > 65536:
                raise ValueError("oversize")
            return json.loads(blob)

        capsule = {"schema": "marco-answer-query-learning-dependencies-v1",
                   "scope": "known_selected_current_query_expression", "status": "partial",
                   "basis": "current_native_selection_and_recorded_acceptance",
                   "input": inp, "items": items, "gaps": gaps}
        try:
            return bounded(capsule)
        except Exception:
            pass
        capsule["items"], capsule["gaps"] = [], [gap("capsule_invalid")]
        try:
            return bounded(capsule)
        except Exception:
            pass
        capsule["input"] = dict.fromkeys(INPUT_KEYS)
        capsule["input"]["model_binding"] = dict.fromkeys(MODEL_KEYS)
        try:
            return bounded(capsule)
        except Exception:
            return {"schema": "marco-answer-query-learning-dependencies-v1",
                    "scope": "known_selected_current_query_expression", "status": "partial",
                    "basis": "current_native_selection_and_recorded_acceptance",
                    "input": dict(dict.fromkeys(INPUT_KEYS), model_binding=dict.fromkeys(MODEL_KEYS)),
                    "items": [], "gaps": [gap("capsule_invalid")]}
    def _respond(self, text):
        with self._guard():
            if self._parser_revision != self._revision():
                self._rehydrate(self.context.snapshot())
            if self._learning_enabled:
                control = self._learning_control_source(text)
                if control is not None:
                    return self._respond_learning(text, control)
            try:
                before = (self._checkpoint_snapshot(), self.turn_counter)
            except ReadingUnavailable:
                # Even the pre-turn snapshot needs an original reading this conversation never
                # archived (e.g. a cleared replay cache over a legacy null pin).  Fall back to the
                # last accepted checkpoint, whose verified semantic cache is restored by
                # ``_rehydrate``; the turn then runs normally against that cache.  Only an operation
                # that actually needs the missing original raises again and is held below.
                before = (copy.deepcopy(self._checkpoint), self.turn_counter)
                self._rehydrate(before[0])
            original_collection = (self._learning, self._learning_gap)
            try:
                prior_collection = (copy.deepcopy(self._learning), copy.deepcopy(self._learning_gap))
            except Exception:
                # optional metadata could not be detached: keep the actual prior references for
                # rollback, record a finite gap, skip passive staging; ordinary turn proceeds
                prior_collection = original_collection
                self._learning_gap = {"code": "collection_failed"}
                stage_collection = False
            else:
                stage_collection = True
            native_before = (self._native_turns, self._native_history_gap)
            native = judged = None
            if self._selected is not None:
                native = read_native_judge_route(text, self._native_pack)
            try:
                try:
                    if native is not None:
                        result, judged = self._native_result(text, native)
                    else:
                        result = self.context.turn(text)
                except ReadingUnavailable:
                    # an operation needed an original reading this conversation never archived:
                    # roll this attempted turn back and ask locally; nothing is re-read
                    self._rehydrate(before[0])
                    return self._result(self._hold("historical_reading_unavailable", text,
                                                   ("unread_event", "input_understanding_failed")))
                self.turn_counter += 1
                unknown_question = result is None
                if result is None:
                    result = self._hold("unresolved", text, ("input_understanding_failed",))
                out = self._result(result)
                out = self._conditional_relation(text, result, out, before[0], native,
                                                 unknown_question=unknown_question)
                if self._active is not None:     # the computed result, kept even if the save below rolls back
                    self._active["computed"] = copy.deepcopy(out)
                    self._active["used"] = None if native is not None else self._used_readings(result)
                if native is not None:
                    self._native_record(text, native, judged, out)
                if self._learning_enabled and stage_collection and native is None:
                    pre_collector = None
                    try:
                        # passive metadata only, collected before the sole save so the carrier is
                        # persisted with it; a failure here restores the prior metadata, records a
                        # finite gap, and never reaches the outer rollback or replaces ``out``
                        pre_collector = (copy.deepcopy(self._learning), copy.deepcopy(self._learning_gap))
                        self._learning_after_ordinary(text, out, before[0])
                    except Exception:
                        if pre_collector is not None:
                            self._learning, self._learning_gap = pre_collector
                        self._learning_gap = {"code": "collection_failed"}
                self.save()
                if (native is None and self._active is not None and isinstance(result, dict)
                        and result.get("status") == "answered"):
                    code = "collector_failed"
                    try:
                        from marco.trace.runtime import plain_json
                        meta = plain_json(self._answer_learning_dependencies(result))
                        code = "collector_metadata_invalid"
                        if (isinstance(meta, dict)
                                and set(meta) == {"schema", "scope", "status", "basis", "items", "gaps"}
                                and meta["schema"] == "marco-answer-learning-dependencies-v1"
                                and meta["scope"] == "known_selected_archived_fact_premises"
                                and meta["status"] == "partial"
                                and meta["basis"] == "result_proof_leaf_and_archived_selection_with_recorded_acceptance"
                                and isinstance(meta["items"], list) and isinstance(meta["gaps"], list)
                                and len(meta["gaps"]) <= 64):
                            blob = json.dumps(meta, ensure_ascii=False, allow_nan=False, sort_keys=True,
                                              separators=(",", ":"))
                            if len(blob.encode("utf-8")) <= 65536:
                                self._active["learning_dependencies"] = json.loads(blob)
                                code = None
                            else:
                                code = "collector_metadata_oversize"
                    except Exception:
                        pass
                    if code is not None:
                        self._active["learning_dependencies"] = {
                            "schema": "marco-answer-learning-dependencies-v1",
                            "scope": "known_selected_archived_fact_premises",
                            "status": "partial",
                            "basis": "result_proof_leaf_and_archived_selection_with_recorded_acceptance",
                            "items": [],
                            "gaps": [{"proof_path": None, "observation_id": None, "reading_revision": None,
                                      "clause_ordinal": None, "code": code}]}
                try:
                    if (native is None and self._active is not None and isinstance(result, dict)
                            and result.get("status") == "answered"):
                        self._active["query_learning_dependencies"] = self._answer_query_learning_dependencies(text, result, out)
                except Exception:
                    pass
                return out
            except BaseException:
                self.turn_counter = before[1]
                self._native_turns, self._native_history_gap = native_before
                if prior_collection is not None:
                    self._learning, self._learning_gap = prior_collection
                self._rehydrate(before[0])
                raise

    def _learning_control_source(self, text):
        # thin: the existing pure control reader decides; None means the ordinary path
        return read_learning_control(self.context._parser_instance, text)

    def _respond_learning(self, text, control):
        """Collect one L1 learning control into the single bounded draft and, on a current
        explicit approve, hand the assembled payload to the native ``_teach`` gate once."""
        import hashlib
        import json

        _KINDS = ("equivalence", "positive", "unrecognized", "approve")
        _NEED = (("ref", "learning_need_equivalent"), ("positive", "learning_need_positive"),
                 ("negative", "learning_need_unrecognized"))

        def _canon(obj):
            return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                              allow_nan=False)

        def _sha(data):
            return hashlib.sha256(data.encode("utf-8")).hexdigest()

        state = {"counted": False, "turn_id": None}

        def _count():
            # Non-admission turn: exactly one counter increment per control, stamped after it.
            if not state["counted"]:
                self.turn_counter += 1
                state["counted"] = True
                state["turn_id"] = "turn_%d" % self.turn_counter
            return state["turn_id"]

        def _hold_local(reason, keys, said=None):
            # Non-admission: count once (if not already), one plain save, reply via _hold/_result.
            _count()
            result = self._result(self._hold(reason, text if said is None else said, keys))
            if self._active is not None:
                self._active["computed"] = copy.deepcopy(result)
            self.save()
            return result

        def _fits(draft):
            try:
                data = _canon(draft)
            except (TypeError, ValueError):
                return False
            limit = getattr(self.memory, "payload_bytes_limit", None)
            if isinstance(limit, int) and len(data.encode("utf-8")) > limit:
                return False
            vlimit = getattr(self.memory, "validation_limit", None)
            if isinstance(vlimit, int):
                total = len(draft.get("positive") or []) + len(draft.get("negative") or [])
                if total > vlimit:
                    return False
            return True

        if isinstance(control, dict) and control.get("expression_kind") == "query":
            return self._respond_query_learning(text, control)
        learning = getattr(self, "_learning", None)
        if not isinstance(learning, dict):
            learning = {"targets": {"pending": None}, "draft": None}
            self._learning = learning
        learning.setdefault("targets", {}).setdefault("pending", None)
        learning.setdefault("draft", None)
        pending = learning["targets"]["pending"]
        binding = self._model_binding()

        # --- L1 shape validation (no inference, no word matching) ---
        if not isinstance(control, dict) or control.get("kind") not in _KINDS \
                or not isinstance(control.get("fields"), dict) or "evidence" not in control:
            return _hold_local("learning_control_invalid", ("learning_control_invalid",))
        kind = control["kind"]
        fields = control["fields"]
        if kind == "equivalence":
            if set(fields) != {"expression", "reference"} \
                    or not isinstance(fields["expression"], str) or not isinstance(fields["reference"], str):
                return _hold_local("learning_control_invalid", ("learning_control_invalid",))
        elif kind == "positive":
            if set(fields) != {"expression", "reference"} \
                    or not isinstance(fields["expression"], str) or not isinstance(fields["reference"], str):
                return _hold_local("learning_control_invalid", ("learning_control_invalid",))
        elif kind == "unrecognized":
            if set(fields) != {"expression"} or not isinstance(fields["expression"], str):
                return _hold_local("learning_control_invalid", ("learning_control_invalid",))
        elif fields:
            return _hold_local("learning_control_invalid", ("learning_control_invalid",))
        try:
            _json(control)
        except (TypeError, ValueError):
            return _hold_local("learning_control_invalid", ("learning_control_invalid",))

        # --- actual pending / binding checks ---
        if not isinstance(pending, dict) or not isinstance(pending.get("text"), str):
            return _hold_local("learning_target_unavailable", ("learning_target_unavailable",))
        if pending.get("model_binding") != binding:
            return _hold_local("learning_model_changed", ("learning_model_changed",))
        if pending.get("accepted") is True:
            return _hold_local("learning_accepted_resubmit_required",
                               ("learning_accepted_resubmit_required",),
                               said=pending["text"])

        def _record(turn_id):
            return {
                "kind": kind,
                "fields": copy.deepcopy(fields),
                "evidence": copy.deepcopy(control["evidence"]),
                "source": {
                    "text": text,
                    "text_sha256": _sha(text),
                    "conversation_id": self.conversation_id,
                    "turn_id": turn_id,
                    "observation_id": None,
                    "input_event_id": None,
                    "provenance_status": "partial",
                    "model_binding": binding,
                },
            }

        draft = learning["draft"]
        if not isinstance(draft, dict):
            # Target capsule: the 8 public keys of the ORIGINAL pending source, stored once.
            draft = {"target": {k: copy.deepcopy(pending.get(k)) for k in self._LESSON_SOURCE_KEYS},
                     "ref": None, "positive": [], "negative": [], "approve": None,
                     "last_attempt_signature": None}
        candidate = copy.deepcopy(draft)
        _MISSING = _NEED
        changed = False     # a NEW substantive record was added to the candidate

        if kind == "equivalence":
            if fields["expression"] != pending["text"]:
                return _hold_local("learning_control_invalid", ("learning_control_invalid",))
            ref = candidate["ref"]
            if isinstance(ref, dict) and isinstance(ref.get("fields"), dict):
                if ref["fields"].get("reference") != fields["reference"]:
                    return _hold_local("learning_draft_conflict", ("learning_draft_conflict",))
                # same reference repeated: keep first witness
                turn_id = _count()
            else:
                turn_id = _count()
                candidate["ref"] = _record(turn_id)
                changed = True
        elif kind in ("positive", "unrecognized"):
            key = "positive" if kind == "positive" else "negative"
            turn_id = _count()
            if not any(isinstance(r, dict) and r.get("fields") == fields for r in candidate[key]):
                candidate[key].append(_record(turn_id))
                changed = True
        else:
            for part, reason in _MISSING:
                if not candidate.get(part):
                    # Incomplete approve: counted non-admission turn, stored draft, one save.
                    turn_id = _count()
                    candidate["approve"] = _record(turn_id)
                    if _fits(candidate):
                        learning["draft"] = candidate
                    return _hold_local(reason, (reason,))
            candidate["approve"] = _record(None)

        if not _fits(candidate):
            # Older valid draft preserved untouched.
            return _hold_local("learning_control_invalid", ("learning_control_invalid",))

        if kind != "approve":
            if changed:
                # a new substantive draft invalidates the old rejected witness markers
                candidate["last_attempt_signature"] = None
                for held in (pending, candidate):
                    held.pop("decision_cid", None)
                    held.pop("decision_head", None)
            learning["draft"] = candidate
            for part, reason in _MISSING:
                if not candidate.get(part):
                    return _hold_local(reason, (reason,))
            return _hold_local("learning_need_approval", ("learning_need_approval",))

        # --- current complete approve: helper once, rejection signature, then one native gate ---
        try:
            assembled = self._learning_payload({k: candidate[k] for k in
                                                ("target", "ref", "positive", "negative", "approve")})
        except ValueError:
            return _hold_local("learning_control_invalid", ("learning_control_invalid",))
        if not isinstance(assembled, dict) or "payload" not in assembled or "lesson" not in assembled:
            return _hold_local("learning_control_invalid", ("learning_control_invalid",))
        payload, lesson = assembled["payload"], assembled["lesson"]
        head = self.memory._store.head()
        signature = _sha(_canon({"payload": payload, "selected_binding": binding,
                                 "memory_before_head": head}))
        if draft.get("last_attempt_signature") == signature:
            # Same failed payload against same head: local rejection, gate not re-run.
            return _hold_local("learning_rejected", ("learning_rejected",))

        learning["draft"] = candidate
        # Native _teach owns the counter increment, the gate and the save exactly once.
        view = self._teach(payload, None, None, lesson=lesson,
                           outcome={"pending": pending, "candidate": candidate, "signature": signature})
        if isinstance(view, dict) and view.get("accepted") is True:
            return self._result(self._hold("learning_accepted_resubmit_required", pending["text"],
                                           ("learning_accepted_resubmit_required",)))
        return self._result(self._hold("learning_rejected", text, ("learning_rejected",)))

    def _learning_after_ordinary(self, text, out, before_snapshot):
        # Passive bounded source collector.  At most one pending record; the first one is kept
        # while other unknown/known/query inputs arrive.  No teaching, parser, Memory or
        # persistence writes; any error is caught by the caller after the ordinary save.
        # ``before_snapshot`` is the ACTUAL pre-turn context snapshot (never inferred from
        # the saved target); its observation_ids are the authoritative attempt boundary.
        self._query_source_capture(text, out)
        targets = self._learning.get("targets") if isinstance(self._learning, dict) else None
        if not isinstance(targets, dict):
            return
        status = out.get("status") if isinstance(out, dict) else None
        snapshot = self.context.snapshot()
        pending = targets.get("pending")
        if pending is not None:
            # clear only an internally accepted target whose exact source was observed THIS
            # turn and now has a REAL NEW archived active reading (never rely on unread
            # disappearance or on historical versions: forget precedes grounding)
            if (isinstance(pending, dict) and pending.get("accepted") is True
                    and isinstance(text, str) and text == pending.get("text")
                    and status == "observed" and isinstance(before_snapshot, dict)):
                ledger = snapshot.get("reading_ledger") or {}
                records = ledger.get("records") if isinstance(ledger, dict) else None
                if not isinstance(records, dict):
                    return
                before_ids = set(before_snapshot.get("observation_ids") or ())
                for oid in snapshot.get("observation_ids") or ():
                    if oid is None or oid in before_ids:
                        continue
                    rec = records.get(oid)
                    if not isinstance(rec, dict):
                        continue
                    versions = rec.get("versions")
                    active = rec.get("active")
                    if (not isinstance(versions, list) or isinstance(active, bool)
                            or not isinstance(active, int) or not 1 <= active <= len(versions)):
                        continue
                    version = versions[active - 1]
                    if (isinstance(version, dict) and version.get("source") == text
                            and version.get("parsed") is not None):
                        targets.pop("pending", None)
                        self._learning["draft"] = None
                        return
            return
        if status != "unresolved":
            return
        if not isinstance(text, str) or "\r" in text or "\n" in text:
            return
        unread = snapshot.get("unread") or ()
        if not any(isinstance(u, dict) and u.get("text") == text for u in unread):
            return
        initial_ids = [oid for oid in (snapshot.get("observation_ids") or ())][:128]
        record = {
            "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "conversation_id": self.conversation_id,
            "turn_id": "turn_%d" % self.turn_counter,
            "observation_id": None,
            "input_event_id": None,
            "provenance_status": "partial",
            "model_binding": self._model_binding(),
            "initial_observation_ids": initial_ids,
            "accepted": False,
        }
        blob = json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":"))
        if len(blob.encode("utf-8")) > self.memory.payload_bytes_limit:
            return
        targets["pending"] = json.loads(blob)

    def _query_source_check(self, env, *, bound_turn=None, bound_head=None):
        # Readonly bounded validation of the optional query-source envelope; returns a detached
        # complete envelope and raises only a controlled ValueError code.
        import hashlib
        import json
        import re
        codes = ("query_source_unavailable", "query_source_invalid", "query_source_owner_unavailable",
                 "query_source_binding_mismatch", "query_source_input_mismatch", "query_source_overflow")
        try:
            if type(env) is not dict or set(env) != {"schema", "source", "gap"} \
                    or type(env["schema"]) is not str or env["schema"] != "marco-query-learning-source-v1":
                raise ValueError("query_source_invalid")
            gap, src = env["gap"], env["source"]
            if gap is not None and (type(gap) is not dict or set(gap) != {"code"}
                                    or type(gap["code"]) is not str or gap["code"] not in codes):
                raise ValueError("query_source_invalid")
            detached_gap = None if gap is None else {"code": gap["code"]}
            limit = getattr(self.memory, "payload_bytes_limit", None)
            if type(limit) is not int or limit <= 0:
                raise ValueError("query_source_invalid")
            cap = min(limit, 32768)
            if src is None:
                result = {"schema": "marco-query-learning-source-v1", "source": None, "gap": detached_gap}
                if len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False).encode("utf-8")) > cap:
                    raise ValueError("query_source_overflow")
                return result
            keys = {"text", "text_sha256", "input_event_id", "conversation_id", "input_turn", "session_turn",
                    "model_binding", "memory_binding", "projection_fingerprint", "producer_status",
                    "provenance_status"}
            if type(src) is not dict or set(src) != keys:
                raise ValueError("query_source_invalid")
            hexre = re.compile(r"[0-9a-f]{64}")
            turn = self.turn_counter if bound_turn is None else bound_turn
            head = self._binding() if bound_head is None else bound_head
            if type(turn) is not int or type(head) is not dict or set(head) != {"seq", "change_id"} \
                    or type(head["seq"]) is not int or head["seq"] < 0:
                raise ValueError("query_source_invalid")
            text, sha, event_id = src["text"], src["text_sha256"], src["input_event_id"]
            if type(text) is not str or not text.strip() or type(sha) is not str or not hexre.fullmatch(sha) \
                    or sha != hashlib.sha256(text.encode("utf-8")).hexdigest():
                raise ValueError("query_source_invalid")
            if type(event_id) is not str or not event_id.strip() or type(src["conversation_id"]) is not str:
                raise ValueError("query_source_invalid")
            input_turn, session_turn = src["input_turn"], src["session_turn"]
            if type(input_turn) is not int or input_turn < 1 or type(session_turn) is not int \
                    or session_turn < 1 or session_turn > turn:
                raise ValueError("query_source_invalid")
            if src["conversation_id"] != self.conversation_id:
                raise ValueError("query_source_binding_mismatch")
            if src["producer_status"] not in ("conditional", "meaning_question") \
                    or type(src["producer_status"]) is not str \
                    or type(src["provenance_status"]) is not str \
                    or src["provenance_status"] != "recorded_input_only":
                raise ValueError("query_source_invalid")
            model_binding, memory_binding = src["model_binding"], src["memory_binding"]
            if type(model_binding) is not dict or set(model_binding) != {
                    "content_fingerprint", "effective_key", "parser_sha256"} \
                    or any(type(v) is not str or not hexre.fullmatch(v) for v in model_binding.values()):
                raise ValueError("query_source_invalid")
            if self._selected is not None or model_binding != self._model_binding():
                raise ValueError("query_source_binding_mismatch")
            if type(memory_binding) is not dict or set(memory_binding) != {"seq", "change_id"}:
                raise ValueError("query_source_invalid")
            seq, change_id = memory_binding["seq"], memory_binding["change_id"]
            if type(seq) is not int or seq < 0 or (seq == 0 and change_id is not None) \
                    or (seq > 0 and (type(change_id) is not str or not change_id.strip())):
                raise ValueError("query_source_invalid")
            if seq > head["seq"]:
                raise ValueError("query_source_binding_mismatch")
            try:
                self._check_binding({"memory_binding": {"seq": seq, "change_id": change_id},
                                     "memory_revision": seq})
            except Exception:
                raise ValueError("query_source_binding_mismatch") from None
            cached = getattr(self.model, "_language_projection", None)
            projection = src["projection_fingerprint"]
            if type(projection) is not str or not hexre.fullmatch(projection):
                raise ValueError("query_source_invalid")
            if not isinstance(cached, dict) or cached.get("fingerprint") != projection:
                raise ValueError("query_source_binding_mismatch")
            ledger = self.trace_ledger
            if ledger is None or getattr(ledger, "fsync", None) is not True:
                raise ValueError("query_source_owner_unavailable")
            try:
                event = ledger.get(event_id)
            except Exception:
                raise ValueError("query_source_unavailable") from None
            if event is None:
                raise ValueError("query_source_unavailable")
            try:
                payload, source, runtime = event["payload"], event["source"], event["runtime"]
                declared = runtime["declared_runtime"]["model"]
                selected = runtime["selected"]["model"]
                expected = {"content_fingerprint": model_binding["content_fingerprint"],
                            "effective_key": model_binding["effective_key"]}
                same = _native_identity_equal(event["kind"], "input_received") \
                    and _native_identity_equal(event["event_id"], event_id) \
                    and _native_identity_equal(source["type"], "dialogue_turn") \
                    and _native_identity_equal(source["conversation"], src["conversation_id"]) \
                    and _native_identity_equal(source["turn"], input_turn) \
                    and _native_identity_equal(payload["text"], text) \
                    and _native_identity_equal(payload["sha256"], sha) \
                    and _native_identity_equal(payload["conversation"], src["conversation_id"]) \
                    and _native_identity_equal(payload["turn"], input_turn) \
                    and _native_identity_equal(payload["execution_status"], "not_started") \
                    and _native_identity_equal(payload["installed_memory_head"], dict(memory_binding)) \
                    and all(_native_identity_equal(declared[k], v) and _native_identity_equal(selected[k], v)
                            for k, v in expected.items())
            except (KeyError, TypeError, AttributeError):
                same = False
            if not same:
                raise ValueError("query_source_input_mismatch")
            result = {"schema": "marco-query-learning-source-v1",
                      "source": {"text": text, "text_sha256": sha, "input_event_id": event_id,
                                 "conversation_id": src["conversation_id"], "input_turn": input_turn,
                                 "session_turn": session_turn, "model_binding": dict(model_binding),
                                 "memory_binding": {"seq": seq, "change_id": change_id},
                                 "projection_fingerprint": projection,
                                 "producer_status": src["producer_status"],
                                 "provenance_status": "recorded_input_only"},
                      "gap": detached_gap}
            if len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")) > cap:
                raise ValueError("query_source_overflow")
            return result
        except Exception as exc:
            raise ValueError(str(exc) if isinstance(exc, ValueError) and str(exc) in codes
                             else "query_source_invalid") from None

    def _query_source_capture(self, text, out):
        # Passive first-source capture from the genuine native query producer; optional errors
        # only update the query-local gap and never touch out, facts, Context or Memory.
        if not self._learning_enabled or not isinstance(self._learning, dict) \
                or self._learning.get("query_source") is not None or not isinstance(out, dict):
            return
        rel = out.get("relation_attempt")
        meaning = out.get("meaning")
        if out.get("status") != "unresolved" or not isinstance(meaning, dict) or meaning.get("act") != "hold" \
                or not isinstance(rel, dict) or rel.get("schema") != "marco-relation-query-dialogue-v1" \
                or rel.get("status") not in ("conditional", "meaning_question"):
            return
        try:
            import hashlib
            active = self._active
            if not isinstance(active, dict) or active.get("trace_kind") != "respond":
                raise ValueError("query_source_owner_unavailable")
            attempt, recorder = active.get("trace_attempt"), active.get("trace_recorder")
            ledger = self.trace_ledger
            if recorder is None or recorder is not self._recorder \
                    or ledger is None or getattr(recorder, "ledger", None) is not ledger \
                    or getattr(self.context, "trace", None) is not ledger \
                    or getattr(ledger, "fsync", None) is not True:
                raise ValueError("query_source_owner_unavailable")
            before = self._binding()
            try:
                recorder._open(attempt)
            except Exception:
                raise ValueError("query_source_owner_unavailable") from None
            source = rel.get("source")
            question = source.get("question") if isinstance(source, dict) else None
            if not isinstance(question, dict) or set(question) != {"input_id", "text"} \
                    or not _native_identity_equal(question["input_id"], attempt.input_id) \
                    or not _native_identity_equal(question["text"], text) \
                    or not _native_identity_equal(attempt.text, text) or type(text) is not str or not text.strip():
                raise ValueError("query_source_input_mismatch")
            if not (attempt.conversation == recorder.conversation == self.conversation_id
                    == getattr(self.context, "conversation_id", None)):
                raise ValueError("query_source_input_mismatch")
            if type(attempt.turn) is not int or attempt.turn < 1 or type(self.turn_counter) is not int \
                    or self.turn_counter < 1:
                raise ValueError("query_source_input_mismatch")
            model_binding = self._model_binding()
            binding = rel.get("binding")
            if self._selected is not None or self._knowledge_binding != self.model.content_fingerprint \
                    or not isinstance(binding, dict) \
                    or not _native_identity_equal(binding.get("schema"), "marco-source-parser-snapshot-v1") \
                    or not _native_identity_equal(binding.get("state_scope"), "frozen_attempt_state") \
                    or not _native_identity_equal(binding.get("conversation_id"), self.conversation_id):
                raise ValueError("query_source_binding_mismatch")
            chosen = binding.get("selected_model")
            installed = binding.get("installed_memory")
            if not isinstance(chosen, dict) or not isinstance(installed, dict) \
                    or not _native_identity_equal(chosen.get("content_fingerprint"),
                                                  model_binding["content_fingerprint"]) \
                    or not _native_identity_equal(chosen.get("effective_key"), model_binding["effective_key"]) \
                    or not _native_identity_equal(chosen.get("base_parser_sha256"),
                                                  model_binding["parser_sha256"]) \
                    or not _native_identity_equal(installed.get("head"), before):
                raise ValueError("query_source_binding_mismatch")
            cached = getattr(self.model, "_language_projection", None)
            if not isinstance(cached, dict) \
                    or not _native_identity_equal(cached.get("fingerprint"), rel.get("projection_fingerprint")):
                raise ValueError("query_source_binding_mismatch")
            record = {"text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                      "input_event_id": attempt.input_id, "conversation_id": self.conversation_id,
                      "input_turn": attempt.turn, "session_turn": self.turn_counter,
                      "model_binding": dict(model_binding), "memory_binding": dict(before),
                      "projection_fingerprint": cached["fingerprint"],
                      "producer_status": rel["status"], "provenance_status": "recorded_input_only"}
            checked = self._query_source_check(
                {"schema": "marco-query-learning-source-v1", "source": record, "gap": None},
                bound_turn=self.turn_counter, bound_head=before)
            if not _native_identity_equal(self._binding(), before):
                raise ValueError("query_source_binding_mismatch")
            self._learning["query_source"] = checked["source"]
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) and str(exc) in (
                "query_source_unavailable", "query_source_invalid", "query_source_owner_unavailable",
                "query_source_binding_mismatch", "query_source_input_mismatch",
                "query_source_overflow") else "query_source_unavailable"
            self._learning["query_source_gap"] = {"code": code}

    def _query_source_pack(self):
        # Readonly bounded envelope (or None); the controlled-gap fallback must fit the cap too.
        import json
        if not self._learning_enabled or not isinstance(self._learning, dict):
            return None
        limit = getattr(self.memory, "payload_bytes_limit", None)
        if type(limit) is not int or limit <= 0:
            return None
        cap = min(limit, 32768)
        source, gap = self._learning.get("query_source"), self._learning.get("query_source_gap")
        if source is None and gap is None:
            return None
        try:
            env = self._query_source_check(
                {"schema": "marco-query-learning-source-v1", "source": source, "gap": gap},
                bound_turn=self.turn_counter, bound_head=self._binding())
            encoded = json.dumps(env, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8")
            if len(encoded) <= cap:
                return env
            code = "query_source_overflow"
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) and str(exc) in (
                "query_source_unavailable", "query_source_invalid", "query_source_owner_unavailable",
                "query_source_binding_mismatch", "query_source_input_mismatch",
                "query_source_overflow") else "query_source_invalid"
        fallback = {"schema": "marco-query-learning-source-v1", "source": None, "gap": {"code": code}}
        try:
            encoded = json.dumps(fallback, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8")
        except Exception:
            return None
        return fallback if len(encoded) <= cap else None

    def query_source(self):
        return self._query_source_pack()

    def _query_record_check(self, record, *, bound_turn, bound_head):
        # Readonly check of one query lesson record against the installed declaration, the actual
        # cached control row and its recorded input event; returns a detached record (wire kept).
        from marco.language.teaching import _query_form, _query_marks, _query_origin_decode
        codes = ("query_learning_unavailable", "query_learning_invalid", "query_learning_overflow",
                 "query_learning_owner_unavailable", "query_learning_input_mismatch",
                 "query_learning_binding_mismatch", "query_learning_witness_missing",
                 "query_learning_witness_ambiguous", "query_learning_gate_uncertain",
                 "query_learning_outcome_failed")
        roles = {"equivalence": ("expression", "reference"), "positive": ("expression", "reference"),
                 "unrecognized": ("expression",), "approve": ()}
        ekeys = {"source", "start", "end", "capture_spans", "fixed_spans", "coverage_status",
                 "declaration_source", "declaration_sha256", "model_binding", "binding_status",
                 "binding_reason", "expression_kind", "form_id", "form_sha256", "selected_control_origin"}

        def canon(value):
            return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")

        def h64(value):
            return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)

        try:
            if (type(bound_turn) is not int or bound_turn < 0 or type(bound_head) is not dict
                    or set(bound_head) != {"seq", "change_id"} or type(bound_head["seq"]) is not int):
                raise ValueError("query_learning_invalid")
            if (type(record) is not dict or set(record) != {"kind", "fields", "evidence", "source"}
                    or type(record["kind"]) is not str or record["kind"] not in roles):
                raise ValueError("query_learning_invalid")
            kind, fields, ev, src = record["kind"], record["fields"], record["evidence"], record["source"]
            want = roles[kind]
            if (type(fields) is not dict or set(fields) != set(want)
                    or any(type(fields[r]) is not str or not fields[r].strip() for r in want)):
                raise ValueError("query_learning_invalid")
            # source: the actual control input itself, never the target
            if type(src) is not dict or set(src) != set(self._LESSON_SOURCE_KEYS):
                raise ValueError("query_learning_invalid")
            text, tid = src["text"], src["turn_id"]
            if (type(text) is not str or not text.strip()
                    or src["text_sha256"] != hashlib.sha256(text.encode("utf-8")).hexdigest()
                    or src["observation_id"] is not None or src["provenance_status"] != "recorded_input_only"
                    or type(src["input_event_id"]) is not str or not src["input_event_id"].strip()):
                raise ValueError("query_learning_invalid")
            binding = self._model_binding()
            if (type(src["conversation_id"]) is not str or src["conversation_id"] != self.conversation_id
                    or self._selected is not None or canon(src["model_binding"]) != canon(binding)):
                raise ValueError("query_learning_binding_mismatch")
            if tid is None and kind != "approve":
                raise ValueError("query_learning_invalid")
            if tid is not None and not (type(tid) is str and tid.startswith("turn_") and tid[5:].isascii()
                                        and tid[5:].isdigit() and str(int(tid[5:])) == tid[5:]
                                        and 0 < int(tid[5:]) <= bound_turn):
                raise ValueError("query_learning_invalid")
            # the unchanged fourteen L1 evidence values plus the encoded origin
            if (type(ev) is not dict or set(ev) != ekeys or type(ev["source"]) is not str or ev["source"] != text
                    or type(ev["start"]) is not int or ev["start"] != 0
                    or type(ev["end"]) is not int or ev["end"] != len(text)
                    or ev["coverage_status"] != "complete"
                    or ev["declaration_source"] != "parser.data.learning_dialogue"
                    or ev["model_binding"] is not None or ev["binding_status"] != "partial"
                    or ev["binding_reason"] != "parser_model_binding_unavailable"
                    or ev["expression_kind"] != "query" or type(ev["form_id"]) is not str
                    or not h64(ev["declaration_sha256"]) or not h64(ev["form_sha256"])):
                raise ValueError("query_learning_invalid")
            caps, fixed = ev["capture_spans"], ev["fixed_spans"]
            if (type(caps) is not dict or set(caps) != set(want) or type(fixed) is not list
                    or len(fixed) > len(want) + 1):
                raise ValueError("query_learning_invalid")
            spans = []
            for sp in [caps[r] for r in want] + fixed:
                if (type(sp) is not dict or set(sp) != {"start", "end", "text"} or type(sp["start"]) is not int
                        or type(sp["end"]) is not int or type(sp["text"]) is not str
                        or not 0 <= sp["start"] < sp["end"] <= len(text)
                        or text[sp["start"]:sp["end"]] != sp["text"]):
                    raise ValueError("query_learning_invalid")
                spans.append((sp["start"], sp["end"]))
            pos = 0
            for start, end in sorted(spans):
                if start != pos:
                    raise ValueError("query_learning_invalid")
                pos = end
            if pos != len(text) or any(caps[r]["text"] != fields[r] for r in want):
                raise ValueError("query_learning_invalid")
            # installed parser declaration == cached projection declaration; one current form and row
            parser = getattr(self.context, "_parser_instance", None)
            cached = getattr(self.model, "_language_projection", None)
            decl = (getattr(parser, "data", None) or {}).get("learning_dialogue")
            if (not isinstance(cached, dict) or not isinstance(cached.get("data"), dict)
                    or type(decl) is not dict or type(decl.get("forms")) is not list
                    or type(cached.get("control_sources")) is not list or not h64(cached.get("fingerprint"))):
                raise ValueError("query_learning_unavailable")
            declared = canon(decl)
            if (declared != canon(cached["data"].get("learning_dialogue"))
                    or hashlib.sha256(declared).hexdigest() != ev["declaration_sha256"]):
                raise ValueError("query_learning_binding_mismatch")
            forms, rows = decl["forms"], cached["control_sources"]
            hits = [i for i, f in enumerate(forms) if isinstance(f, dict) and f.get("id") == ev["form_id"]]
            if len(hits) != 1 or len(rows) != len(forms):
                raise ValueError("query_learning_binding_mismatch")
            index = hits[0]
            form, row = forms[index], rows[index]
            if (not isinstance(row, dict) or row.get("id") != ev["form_id"]
                    or form.get("expression_kind") != "query" or form.get("kind") != kind
                    or hashlib.sha256(canon(form)).hexdigest() != ev["form_sha256"]
                    or row.get("form_sha256") != ev["form_sha256"]):
                raise ValueError("query_learning_binding_mismatch")
            delims = _query_form(form, _query_marks(parser))
            if set(delims) != set(want) or not text.strip().startswith(form["ownership_prefix"]):
                raise ValueError("query_learning_invalid")
            for r in want:
                start, end = caps[r]["start"], caps[r]["end"]
                if start < 1 or end >= len(text) or text[start - 1] != delims[r][0] or text[end] != delims[r][1]:
                    raise ValueError("query_learning_invalid")
            # the installed parser's own pure L1 reader must read the recorded input as exactly this control
            control = read_learning_control(parser, text)
            original = {k: v for k, v in ev.items() if k != "selected_control_origin"}
            if (not isinstance(control, dict) or control.get("expression_kind") != "query"
                    or canon({"kind": control.get("kind"), "fields": control.get("fields"),
                              "evidence": control.get("evidence")})
                    != canon({"kind": kind, "fields": fields, "evidence": original})):
                raise ValueError("query_learning_invalid")
            # the decoded logical origin must be byte-identical to the actual cached row
            _, actual = _query_origin_decode(ev["selected_control_origin"])
            if actual != canon({"projection_fingerprint": cached["fingerprint"], "control_index": index,
                                "control_source": row}):
                raise ValueError("query_learning_binding_mismatch")
            # the actual recorded input event of this control (current or historical)
            ledger = self.trace_ledger
            if ledger is None or getattr(ledger, "fsync", None) is not True:
                raise ValueError("query_learning_owner_unavailable")
            try:
                event = ledger.get(src["input_event_id"])
            except Exception:
                raise ValueError("query_learning_unavailable") from None
            if event is None:
                raise ValueError("query_learning_unavailable")
            installed = None
            try:
                payload, origin, runtime = event["payload"], event["source"], event["runtime"]
                installed = payload["installed_memory_head"]
                expect = {"content_fingerprint": binding["content_fingerprint"],
                          "effective_key": binding["effective_key"]}
                same = (_native_identity_equal(event["kind"], "input_received")
                        and _native_identity_equal(event["epistemic_status"], "reported")
                        and _native_identity_equal(event["event_id"], src["input_event_id"])
                        and _native_identity_equal(origin["type"], "dialogue_turn")
                        and _native_identity_equal(origin["conversation"], self.conversation_id)
                        and _native_identity_equal(payload["conversation"], self.conversation_id)
                        and _native_identity_equal(payload["text"], text)
                        and _native_identity_equal(payload["sha256"], src["text_sha256"])
                        and _native_identity_equal(payload["execution_status"], "not_started")
                        and type(payload["turn"]) is int and payload["turn"] >= 1
                        and _native_identity_equal(origin["turn"], payload["turn"])
                        and all(_native_identity_equal(runtime["declared_runtime"]["model"][k], v)
                                and _native_identity_equal(runtime["selected"]["model"][k], v)
                                for k, v in expect.items()))
            except (KeyError, TypeError, AttributeError):
                same = False
            if (not same or type(installed) is not dict or set(installed) != {"seq", "change_id"}
                    or type(installed["seq"]) is not int or installed["seq"] > bound_head["seq"]):
                raise ValueError("query_learning_input_mismatch")
            try:
                self._check_binding({"memory_binding": dict(installed), "memory_revision": installed["seq"]})
            except Exception:
                raise ValueError("query_learning_binding_mismatch") from None
            return _json(record)
        except Exception as exc:
            raise ValueError(str(exc) if isinstance(exc, ValueError) and str(exc) in codes
                             else "query_learning_invalid") from None

    def _query_control_record(self, text, control, *, turn_id):
        # The current actual control input as a native lesson record whose evidence carries the
        # encoded current selected origin; no counter, save or state mutation.
        from marco.language.teaching import _query_origin_encode
        codes = ("query_learning_unavailable", "query_learning_invalid", "query_learning_overflow",
                 "query_learning_owner_unavailable", "query_learning_input_mismatch",
                 "query_learning_binding_mismatch")
        try:
            if (type(control) is not dict or set(control) != {"kind", "fields", "evidence", "expression_kind"}
                    or control["expression_kind"] != "query" or type(text) is not str):
                raise ValueError("query_learning_invalid")
            control = _json(control)
            evidence = control["evidence"]
            if (type(evidence) is not dict or "selected_control_origin" in evidence
                    or type(evidence.get("form_id")) is not str):
                raise ValueError("query_learning_invalid")
            active, ledger = self._active, self.trace_ledger
            if not isinstance(active, dict) or active.get("trace_kind") != "respond":
                raise ValueError("query_learning_owner_unavailable")
            attempt, recorder = active.get("trace_attempt"), active.get("trace_recorder")
            if (recorder is None or recorder is not self._recorder or ledger is None
                    or getattr(recorder, "ledger", None) is not ledger
                    or getattr(self.context, "trace", None) is not ledger
                    or getattr(ledger, "fsync", None) is not True):
                raise ValueError("query_learning_owner_unavailable")
            try:
                recorder._open(attempt)
            except Exception:
                raise ValueError("query_learning_owner_unavailable") from None
            if (not _native_identity_equal(attempt.text, text) or type(attempt.turn) is not int
                    or attempt.turn < 1
                    or not (attempt.conversation == recorder.conversation == self.conversation_id
                            == getattr(self.context, "conversation_id", None))):
                raise ValueError("query_learning_input_mismatch")
            head = self._binding()
            event = ledger.get(attempt.input_id)
            if (not isinstance(event, dict) or not isinstance(event.get("payload"), dict)
                    or not _native_identity_equal(event["payload"].get("installed_memory_head"), head)):
                raise ValueError("query_learning_binding_mismatch")
            if self._selected is not None or self._knowledge_binding != self.model.content_fingerprint:
                raise ValueError("query_learning_binding_mismatch")
            cached = getattr(self.model, "_language_projection", None)
            parser = getattr(self.context, "_parser_instance", None)
            decl = (getattr(parser, "data", None) or {}).get("learning_dialogue")
            forms = decl.get("forms") if isinstance(decl, dict) else None
            rows = cached.get("control_sources") if isinstance(cached, dict) else None
            if type(forms) is not list or type(rows) is not list or len(rows) != len(forms):
                raise ValueError("query_learning_unavailable")
            hits = [i for i, f in enumerate(forms) if isinstance(f, dict) and f.get("id") == evidence["form_id"]]
            if len(hits) != 1:
                raise ValueError("query_learning_binding_mismatch")
            origin = {"projection_fingerprint": cached.get("fingerprint"), "control_index": hits[0],
                      "control_source": copy.deepcopy(rows[hits[0]])}
            try:
                evidence["selected_control_origin"] = _query_origin_encode(origin)
            except ValueError as exc:
                raise ValueError("query_learning_overflow" if str(exc) == "query_origin_overflow"
                                 else "query_learning_invalid") from None
            record = {"kind": control["kind"], "fields": control["fields"], "evidence": evidence,
                      "source": {"text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                                 "conversation_id": self.conversation_id, "turn_id": turn_id,
                                 "observation_id": None, "input_event_id": attempt.input_id,
                                 "provenance_status": "recorded_input_only",
                                 "model_binding": self._model_binding()}}
            bound = self.turn_counter + 1 if turn_id is not None else self.turn_counter
            return self._query_record_check(record, bound_turn=bound, bound_head=head)
        except Exception as exc:
            raise ValueError(str(exc) if isinstance(exc, ValueError) and str(exc).startswith("query_learning_")
                             and (str(exc) in codes or str(exc).startswith("query_learning_witness"))
                             else "query_learning_invalid") from None

    def _query_learning_check(self, env, *, bound_turn=None, bound_head=None):
        # Readonly check of the optional query-draft envelope: exact binding to the protected source
        # carrier, every record, aggregate expanded origin bytes, the finite wire and the actual native
        # decision witnesses.  Returns a detached envelope or raises one controlled ValueError code.
        from marco.language.teaching import _query_origin_decode
        codes = ("query_learning_unavailable", "query_learning_invalid", "query_learning_overflow",
                 "query_learning_owner_unavailable", "query_learning_input_mismatch",
                 "query_learning_binding_mismatch", "query_learning_witness_missing",
                 "query_learning_witness_ambiguous", "query_learning_gate_uncertain",
                 "query_learning_outcome_failed")
        schema = "marco-query-learning-draft-v2"
        marks = ("decision_cid", "decision_head")
        five = ("target", "ref", "positive", "negative", "approve")

        def canon(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

        def sha(value):
            return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()

        def h64(value):
            return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)

        def memb(m):
            return (type(m) is dict and set(m) == {"seq", "change_id"} and type(m["seq"]) is int and m["seq"] >= 0
                    and (m["change_id"] is None if m["seq"] == 0
                         else type(m["change_id"]) is str and m["change_id"].strip() != ""))

        def turn_of(tid):
            if (type(tid) is str and tid.startswith("turn_") and tid[5:].isascii() and tid[5:].isdigit()
                    and str(int(tid[5:])) == tid[5:]):
                return int(tid[5:])
            return None

        def payload_of(draft):
            return {"text": draft["target"]["text"], "equivalent": draft["ref"]["fields"]["reference"],
                    "validation": [{"id": "positive_%d" % (i + 1), "text": r["fields"]["expression"],
                                    "equivalent": r["fields"]["reference"]} for i, r in enumerate(draft["positive"])]
                    + [{"id": "negative_%d" % (i + 1), "text": r["fields"]["expression"], "unrecognized": True}
                       for i, r in enumerate(draft["negative"])]}

        def body_of(cand):
            # exactly one native ADD_RULE of the candidate's own rule, tied to this candidate id
            ev = cand.get("evidence")
            ev = ev if isinstance(ev, dict) else {}
            found = [d["payload"]["body"] for d in (cand.get("deltas") or [])
                     if isinstance(d, dict) and d.get("op") == "ADD_RULE" and d.get("target_kind") == "rule"
                     and d.get("target_id") == ev.get("rule_id") and isinstance(d.get("payload"), dict)
                     and "body" in d["payload"]]
            body = found[0] if len(found) == 1 else None
            if (not isinstance(body, dict) or not isinstance(body.get("provenance"), dict)
                    or ev.get("candidate_id") != cand.get("candidate_id") or ev.get("kind") != "expression"
                    or body.get("schema") != "marco-learning-memory-v1"
                    or body.get("supervision") != "explicit_user_teaching"):
                raise ValueError("query_learning_witness_missing")
            return body

        def records(draft, turn, head):
            # every record occurrence, each decoded and re-canonicalized, summed without dedup
            items = [(draft["ref"], "equivalence")] if draft["ref"] is not None else []
            items += [(r, "positive") for r in draft["positive"]] + [(r, "unrecognized") for r in draft["negative"]]
            items += [(draft["approve"], "approve")] if draft["approve"] is not None else []
            total = 0
            for rec, kind in items:
                if self._query_record_check(rec, bound_turn=turn, bound_head=head)["kind"] != kind:
                    raise ValueError("query_learning_invalid")
                total += len(_query_origin_decode(rec["evidence"]["selected_control_origin"])[1])
                if total > 262144:
                    raise ValueError("query_learning_overflow")
            if draft["ref"] is not None and draft["ref"]["fields"]["expression"] != draft["target"]["text"]:
                raise ValueError("query_learning_invalid")
            for part in ("positive", "negative"):
                seen = [canon(r["fields"]) for r in draft[part]]
                if len(set(seen)) != len(seen):
                    raise ValueError("query_learning_invalid")

        def witness(pending, draft, head):
            # actual candidate, exact ADD_RULE body, lesson/payload/provenance and decision identity
            if draft is None:
                raise ValueError("query_learning_witness_missing")
            cid, dhead = pending.get("decision_cid"), pending.get("decision_head")
            sig, appr = draft["last_attempt_signature"], draft["approve"]
            if (type(cid) is not str or not cid.strip() or draft.get("decision_cid") != cid or not memb(dhead)
                    or canon(draft.get("decision_head")) != canon(dhead) or dhead["seq"] > head["seq"]
                    or pending["accepted"] == (sig is not None) or draft["ref"] is None
                    or not draft["positive"] or not draft["negative"] or appr is None
                    or turn_of(appr["source"]["turn_id"]) is None):
                raise ValueError("query_learning_witness_missing")
            try:
                self._check_binding({"memory_binding": dict(dhead), "memory_revision": dhead["seq"]})
            except Exception:
                raise ValueError("query_learning_binding_mismatch") from None
            cand = self.memory._store.candidate(cid)
            if not isinstance(cand, dict) or cand.get("candidate_id") != cid:
                raise ValueError("query_learning_witness_missing")
            if cand.get("status") == "pending":
                raise ValueError("query_learning_gate_uncertain")
            body = body_of(cand)
            report, payload = body.get("report"), payload_of(draft)
            prov = {"conversation_id": self.conversation_id, "turn_id": appr["source"]["turn_id"],
                    "lesson": {k: draft[k] for k in five}}
            if (body.get("kind") != "expression" or not isinstance(report, dict)
                    or report.get("induction_policy") != "selected-reference-query-slots-v1"
                    or canon(body.get("payload")) != canon(payload) or canon(body["provenance"]) != canon(prov)):
                raise ValueError("query_learning_witness_missing")
            views = [v for v in self.memory.candidates() if v.get("candidate_id") == cid]
            view = views[0] if len(views) == 1 else {}
            want = ("active", "retracted", "superseded") if pending["accepted"] else ("rejected",)
            if (view.get("status") not in want or view.get("accepted") is not pending["accepted"]
                    or canon(view.get("report")) != canon(report)
                    or canon(view.get("provenance")) != canon(body["provenance"])):
                raise ValueError("query_learning_witness_missing")
            if pending["accepted"]:
                seq, rid = cand.get("change_seq"), cand["evidence"].get("rule_id")
                change = (self.memory._store.change(seq)
                          if cand.get("status") == "approved" and type(seq) is int else None)
                adds = [d for d in ((change or {}).get("deltas") or []) if isinstance(d, dict)
                        and d.get("op") == "ADD_RULE" and d.get("target_kind") == "rule"
                        and d.get("target_id") == rid]
                cev, cap = (change or {}).get("evidence"), (change or {}).get("approval")
                if (not isinstance(change, dict) or change.get("seq") != seq or report.get("accepted") is not True
                        or canon({"seq": seq, "change_id": change.get("change_id")}) != canon(dhead)
                        or len(adds) != 1 or canon((adds[0].get("payload") or {}).get("body")) != canon(body)
                        or not isinstance(cev, dict) or cev.get("candidate_id") != cid or cev.get("rule_id") != rid
                        or not isinstance(cap, dict) or cap.get("candidate_id") != cid):
                    raise ValueError("query_learning_witness_missing")
            else:
                proposed = cand.get("proposed_at_seq")
                if (cand.get("status") != "rejected" or type(proposed) is not int or proposed != dhead["seq"]
                        or dhead["change_id"] != (self.memory._store.change(proposed)["change_id"] if proposed else None)
                        or sig != sha({"payload": payload, "selected_binding": self._model_binding(),
                                       "memory_before_head": [dhead["seq"], dhead["change_id"]]})):
                    raise ValueError("query_learning_witness_missing")

        def reconcile(pending, draft, turn, head):
            # any other native body with this exact target/ref/examples blocks a second gate; a unique
            # decided one inside the saved counter authority is reconciled read-only
            cid = pending.get("decision_cid")
            mine = self.memory._store.candidate(cid) if cid is not None else None
            at = turn_of(draft["approve"]["source"]["turn_id"]) if cid is not None and draft["approve"] else None
            same = []
            for cand in self.memory._store.candidates():
                try:
                    prov = body_of(cand)["provenance"]
                    if cand.get("candidate_id") == cid or not all(
                            canon(prov["lesson"][k]) == canon(draft[k]) for k in five[:4]):
                        continue
                except Exception:
                    continue
                appr = prov["lesson"].get("approve")
                src = appr.get("source") if isinstance(appr, dict) else None
                stamp = turn_of(src.get("turn_id")) if isinstance(src, dict) else None
                seq = cand.get("proposed_at_seq")
                if (isinstance(mine, dict) and at is not None and stamp is not None and stamp < at
                        and cand.get("status") == "rejected" and type(seq) is int
                        and type(mine.get("proposed_at_seq")) is int and seq <= mine["proposed_at_seq"]):
                    try:    # skip only an earlier rejection re-verified by the whole records/witness check
                        old = {"seq": seq, "change_id": self.memory._store.change(seq)["change_id"] if seq else None}
                        sig = sha({"payload": payload_of(draft), "selected_binding": self._model_binding(),
                                   "memory_before_head": [seq, old["change_id"]]})
                        prior = {**draft, "approve": appr, "last_attempt_signature": sig,
                                 "decision_cid": cand["candidate_id"], "decision_head": old}
                        records(prior, turn, head)
                        witness({**pending, "accepted": False, "decision_cid": cand["candidate_id"],
                                 "decision_head": dict(old)}, prior, head)
                        continue
                    except Exception:
                        pass    # unverified, accepted, pending, future or ambiguous evidence keeps blocking
                same.append(cand)
            if len(same) > 1:
                raise ValueError("query_learning_witness_ambiguous")
            if not same:
                return pending, draft
            cand = same[0]
            approve = body_of(cand)["provenance"]["lesson"].get("approve")
            stamp = (turn_of(approve["source"].get("turn_id"))
                     if isinstance(approve, dict) and isinstance(approve.get("source"), dict) else None)
            if cid is not None or stamp is None or stamp > turn or cand.get("status") not in ("approved", "rejected"):
                raise ValueError("query_learning_gate_uncertain")
            accepted = cand["status"] == "approved"
            seq = cand.get("change_seq") if accepted else cand.get("proposed_at_seq")
            if type(seq) is not int or seq < 0:
                raise ValueError("query_learning_gate_uncertain")
            dhead = {"seq": seq, "change_id": self.memory._store.change(seq)["change_id"] if seq else None}
            sig = None if accepted else sha({"payload": payload_of(draft), "selected_binding": self._model_binding(),
                                             "memory_before_head": [dhead["seq"], dhead["change_id"]]})
            pending = {**pending, "accepted": accepted, "decision_cid": cand["candidate_id"], "decision_head": dhead}
            draft = {**draft, "approve": approve, "last_attempt_signature": sig,
                     "decision_cid": cand["candidate_id"], "decision_head": dict(dhead)}
            records(draft, turn, head)
            witness(pending, draft, head)
            return pending, draft

        try:
            limit = getattr(self.memory, "payload_bytes_limit", None)
            vlimit = getattr(self.memory, "validation_limit", None)
            if type(limit) is not int or limit <= 0 or type(vlimit) is not int or vlimit <= 0:
                raise ValueError("query_learning_unavailable")
            cap = min(limit, 32768)
            gap = env.get("gap") if type(env) is dict else None
            if (type(env) is not dict or type(env.get("schema")) is not str or env["schema"] != schema
                    or not (gap is None or (type(gap) is dict and set(gap) == {"code"}
                                            and type(gap["code"]) is str and gap["code"] in codes))):
                raise ValueError("query_learning_invalid")
            if len(canon(env).encode("utf-8")) > cap:
                raise ValueError("query_learning_overflow")
            if set(env) == {"schema", "gap"}:
                return _json(env)
            if set(env) != {"schema", "source_sha256", "conversation_id", "model_binding", "memory_binding",
                            "turn_counter", "pending", "draft", "gap"}:
                raise ValueError("query_learning_invalid")
            turn = self.turn_counter if bound_turn is None else bound_turn
            head = self._binding() if bound_head is None else bound_head
            if (type(turn) is not int or not memb(head) or type(env["turn_counter"]) is not int
                    or env["turn_counter"] != turn or not memb(env["memory_binding"])
                    or canon(env["memory_binding"]) != canon(head)
                    or type(env["conversation_id"]) is not str or env["conversation_id"] != self.conversation_id
                    or self._selected is not None or canon(env["model_binding"]) != canon(self._model_binding())):
                raise ValueError("query_learning_binding_mismatch")
            carrier = self._learning.get("query_source") if isinstance(self._learning, dict) else None
            if type(carrier) is not dict or not h64(env["source_sha256"]) or sha(carrier) != env["source_sha256"]:
                raise ValueError("query_learning_binding_mismatch")
            target = {"text": carrier["text"], "text_sha256": carrier["text_sha256"],
                      "conversation_id": carrier["conversation_id"],
                      "turn_id": "turn_%d" % carrier["session_turn"], "observation_id": None,
                      "input_event_id": carrier["input_event_id"], "provenance_status": "recorded_input_only",
                      "model_binding": carrier["model_binding"]}
            pending, draft = env["pending"], env["draft"]
            pkeys = set(self._LESSON_SOURCE_KEYS) | {"accepted"}
            dkeys = set(five) | {"last_attempt_signature"}
            if pending is None and draft is not None:
                raise ValueError("query_learning_invalid")
            if pending is not None and (type(pending) is not dict or not pkeys <= set(pending) <= pkeys | set(marks)
                                        or type(pending["accepted"]) is not bool
                                        or canon({k: pending[k] for k in self._LESSON_SOURCE_KEYS})
                                        != canon(target)):
                raise ValueError("query_learning_invalid")
            if draft is not None:
                if (type(draft) is not dict or not dkeys <= set(draft) <= dkeys | set(marks)
                        or canon(draft["target"]) != canon(target)
                        or type(draft["positive"]) is not list or type(draft["negative"]) is not list
                        or len(draft["positive"]) + len(draft["negative"]) > vlimit
                        or not (draft["last_attempt_signature"] is None or h64(draft["last_attempt_signature"]))):
                    raise ValueError("query_learning_invalid")
                records(draft, turn, head)
            if pending is not None:
                if pending["accepted"] or (draft is not None and draft["last_attempt_signature"] is not None):
                    witness(pending, draft, head)
                elif any(k in pending for k in marks) or (draft is not None and any(k in draft for k in marks)):
                    raise ValueError("query_learning_witness_missing")
                if draft is not None and draft["ref"] is not None and draft["positive"] and draft["negative"]:
                    pending, draft = reconcile(pending, draft, turn, head)
            result = _json({**env, "pending": pending, "draft": draft})
            if len(canon(result).encode("utf-8")) > cap:
                raise ValueError("query_learning_overflow")
            return result
        except Exception as exc:
            raise ValueError(str(exc) if isinstance(exc, ValueError) and str(exc) in codes
                             else "query_learning_invalid") from None

    def _query_learning_pack(self):
        # Readonly bounded optional query-draft envelope (or None); a gap-only fallback must fit too.
        schema = "marco-query-learning-draft-v2"
        if not self._learning_enabled or not isinstance(self._learning, dict):
            return None
        pair, gap = self._learning.get("query_draft"), self._learning.get("query_draft_gap")
        if pair is None and gap is None:
            return None
        limit = getattr(self.memory, "payload_bytes_limit", None)
        if type(limit) is not int or limit <= 0:
            return None
        try:
            if pair is None:
                env = {"schema": schema, "gap": gap}
            elif type(pair) is not dict or set(pair) != {"pending", "draft"}:
                raise ValueError("query_learning_invalid")
            else:
                carrier = self._learning.get("query_source")
                env = {"schema": schema,
                       "source_sha256": hashlib.sha256(json.dumps(
                           carrier, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode("utf-8")).hexdigest(),
                       "conversation_id": self.conversation_id, "model_binding": self._model_binding(),
                       "memory_binding": self._binding(), "turn_counter": self.turn_counter,
                       "pending": pair["pending"], "draft": pair["draft"], "gap": gap}
            return self._query_learning_check(env)
        except Exception as exc:
            code = (str(exc) if isinstance(exc, ValueError) and str(exc).startswith("query_learning_")
                    and len(str(exc)) <= 64 else "query_learning_invalid")
            if isinstance(gap, dict) and gap.get("code") in (
                    "query_learning_gate_uncertain", "query_learning_witness_missing",
                    "query_learning_witness_ambiguous", "query_learning_outcome_failed"):
                code = gap["code"]     # a known post-gate uncertainty keeps blocking a duplicate gate
        fallback = {"schema": schema, "gap": {"code": code}}
        try:
            encoded = json.dumps(fallback, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8")
        except Exception:
            return None
        return fallback if len(encoded) <= min(limit, 32768) else None

    def _respond_query_learning(self, text, control):
        """Collect one graph-declared query control into the private query draft and, on a new
        complete current approve, hand the assembled lesson once to the native ``_teach`` gate."""
        schema = "marco-query-learning-draft-v2"
        five = ("target", "ref", "positive", "negative", "approve")
        learning = self._learning
        if not isinstance(learning, dict):
            learning = {}
        prior = {k: copy.deepcopy(learning[k]) for k in ("query_draft", "query_draft_gap") if k in learning}
        prior_turn = self.turn_counter
        binding = self._model_binding()
        blocked = (prior.get("query_draft_gap") or {}).get("code") in (
            "query_learning_gate_uncertain", "query_learning_witness_missing",
            "query_learning_witness_ambiguous", "query_learning_outcome_failed")

        def canon(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

        def restore(counter=True):
            for key in ("query_draft", "query_draft_gap"):
                if key in prior:
                    learning[key] = copy.deepcopy(prior[key])
                else:
                    learning.pop(key, None)
            if counter:
                self.turn_counter = prior_turn

        def hold(reason, code=None, said=None):
            # Non-admission: one counter increment, one save, the selected reply (or None).
            self.turn_counter = prior_turn + 1
            if code is not None and not blocked:
                learning["query_draft_gap"] = {"code": code}
            result = self._result(self._hold(reason, text if said is None else said, (reason,)))
            if self._active is not None:
                self._active["computed"] = copy.deepcopy(result)
            try:
                self.save()
            except BaseException:
                restore()
                raise
            return result

        def failure(exc):
            ok = isinstance(exc, ValueError) and str(exc).startswith("query_learning_")
            return str(exc) if ok else "query_learning_invalid"

        if (type(control) is not dict or set(control) != {"kind", "fields", "evidence", "expression_kind"}
                or control.get("kind") not in ("equivalence", "positive", "unrecognized", "approve")
                or control.get("expression_kind") != "query"):
            return hold("learning_control_invalid", "query_learning_invalid")
        kind = control["kind"]
        env = self.query_source()
        carrier = env.get("source") if isinstance(env, dict) else None
        if not isinstance(carrier, dict):
            return hold("learning_target_unavailable", "query_learning_unavailable")
        target = {"text": carrier["text"], "text_sha256": carrier["text_sha256"],
                  "conversation_id": carrier["conversation_id"], "turn_id": "turn_%d" % carrier["session_turn"],
                  "observation_id": None, "input_event_id": carrier["input_event_id"],
                  "provenance_status": "recorded_input_only", "model_binding": carrier["model_binding"]}
        pair = learning.get("query_draft")
        if pair is not None and (type(pair) is not dict or set(pair) != {"pending", "draft"}
                                 or type(pair["pending"]) is not dict
                                 or canon({k: pair["pending"].get(k) for k in self._LESSON_SOURCE_KEYS})
                                 != canon(target)):
            return hold("learning_control_invalid", "query_learning_invalid")
        pending = copy.deepcopy(pair["pending"]) if pair is not None else {**copy.deepcopy(target), "accepted": False}
        candidate = copy.deepcopy(pair["draft"]) if pair is not None else None
        if canon(pending.get("model_binding")) != canon(binding):
            return hold("learning_model_changed", "query_learning_binding_mismatch")
        if pending.get("accepted") is True:
            packed = self._query_learning_pack()
            if (not isinstance(packed, dict) or not isinstance(packed.get("pending"), dict)
                    or packed["pending"].get("accepted") is not True):
                code = ((packed or {}).get("gap") or {}).get("code")
                return hold("learning_control_invalid", code or "query_learning_witness_missing")
            return hold("learning_accepted_resubmit_required", said=pending["text"])
        if not isinstance(candidate, dict):
            candidate = {"target": copy.deepcopy(target), "ref": None, "positive": [], "negative": [],
                         "approve": None, "last_attempt_signature": None}
        staged = kind == "approve" and bool(candidate["ref"] and candidate["positive"] and candidate["negative"])
        try:
            record = self._query_control_record(text, control,
                                                turn_id=None if staged else "turn_%d" % (prior_turn + 1))
        except ValueError as exc:
            return hold("learning_control_invalid", failure(exc))
        changed, staged_approve = False, None
        if kind == "equivalence":
            if record["fields"]["expression"] != target["text"]:
                return hold("learning_control_invalid", "query_learning_invalid")
            if isinstance(candidate["ref"], dict):
                if candidate["ref"]["fields"]["reference"] != record["fields"]["reference"]:
                    return hold("learning_draft_conflict")
            else:
                candidate["ref"], changed = record, True
        elif kind in ("positive", "unrecognized"):
            part = "positive" if kind == "positive" else "negative"
            if not any(canon(r["fields"]) == canon(record["fields"]) for r in candidate[part]):
                candidate[part].append(record)
                changed = True
        else:
            staged_approve = record if candidate.get("decision_cid") is not None else None
            candidate["approve"] = candidate["approve"] if staged_approve else record
        if changed:
            # a new substantive record invalidates only old rejected decision/signature markers
            candidate["last_attempt_signature"] = None
            for held in (pending, candidate):
                held.pop("decision_cid", None)
                held.pop("decision_head", None)
        envelope = {"schema": schema, "source_sha256": hashlib.sha256(canon(carrier).encode("utf-8")).hexdigest(),
                    "conversation_id": self.conversation_id, "model_binding": binding,
                    "memory_binding": self._binding(), "turn_counter": prior_turn + 1, "pending": pending,
                    "draft": candidate, "gap": learning.get("query_draft_gap")}
        try:
            checked = self._query_learning_check(envelope, bound_turn=prior_turn + 1)
        except ValueError as exc:
            return hold("learning_control_invalid", failure(exc))
        if canon(checked["pending"]) != canon(pending):
            # an exact existing native decision was reconciled read-only: never a second gate
            learning["query_draft"] = {"pending": checked["pending"], "draft": checked["draft"]}
            if checked["pending"]["accepted"]:
                return hold("learning_accepted_resubmit_required", said=pending["text"])
            return hold("learning_rejected")
        if not staged:
            learning["query_draft"] = {"pending": pending, "draft": candidate}
            for part, reason in (("ref", "learning_need_equivalent"), ("positive", "learning_need_positive"),
                                 ("negative", "learning_need_unrecognized")):
                if not candidate[part]:
                    return hold(reason)
            return hold("learning_need_approval")

        if blocked:
            return hold("learning_control_invalid")
        if staged_approve is not None:
            candidate["approve"] = staged_approve
        # --- new complete current approve: helper once, signature, prefit, then one native gate ---
        try:
            assembled = self._learning_payload({k: candidate[k] for k in five})
        except ValueError as exc:
            return hold("learning_control_invalid", "query_learning_overflow"
                        if str(exc).startswith("learning_budget_exceeded") else "query_learning_invalid")
        payload, lesson = assembled["payload"], assembled["lesson"]
        before_head = self.memory._store.head()
        signature = hashlib.sha256(canon({"payload": payload, "selected_binding": binding,
                                          "memory_before_head": list(before_head)}).encode("utf-8")).hexdigest()
        if candidate.get("last_attempt_signature") == signature:
            return hold("learning_rejected")
        # detached byte forecast with the actual next counter; native _teach still owns the stamp
        limit = getattr(self.memory, "payload_bytes_limit", None)
        room = getattr(self.memory, "candidate_limit", None)
        try:
            stamp = "turn_%d" % (self.turn_counter + 1)
            forecast = copy.deepcopy(lesson)
            forecast["approve"]["source"]["conversation_id"] = self.conversation_id
            forecast["approve"]["source"]["turn_id"] = stamp
            wire = dumps({"payload": payload, "provenance": {"conversation_id": self.conversation_id,
                                                             "turn_id": stamp, "lesson": forecast}})
            before_rows = [(c["candidate_id"], dumps(c)) for c in self.memory._store.candidates()]
            before_ids = [i for i, _ in before_rows]
            fits = (type(limit) is int and len(wire.encode("utf-8")) <= min(limit, 32768)
                    and type(room) is int and len(before_ids) < room)
        except Exception:
            fits = False
        if not fits:
            return hold("learning_control_invalid", "query_learning_overflow")
        for held in (pending, candidate):
            held.pop("decision_cid", None)
            held.pop("decision_head", None)
        candidate["last_attempt_signature"] = None
        learning["query_draft"] = {"pending": pending, "draft": candidate}
        learning["query_draft_gap"] = {"code": "query_learning_gate_uncertain"}
        observed = {"before_head": list(before_head), "before_candidate_ids": before_ids, "after_head": None,
                    "after_candidate_ids": None, "new_candidate_ids": None, "view_candidate_id": None,
                    "status": "uncertain"}

        def observe():
            # readonly actual after-state; never reruns, approves or rejects anything
            now = [(c["candidate_id"], dumps(c)) for c in self.memory._store.candidates()]
            observed.update(after_head=list(self.memory._store.head()), after_candidate_ids=[i for i, _ in now])
            observed["new_candidate_ids"] = [i for i in observed["after_candidate_ids"] if i not in before_ids]
            return now == before_rows

        try:
            view = self._teach(payload, None, None, lesson=lesson,
                               outcome={"pending": pending, "candidate": candidate, "signature": signature},
                               expression_kind="query")
        except BaseException:
            # observe only: no rerun, no approval/rejection, no fabricated rollback after a decision
            learning["query_draft_gap"] = {"code": "query_learning_gate_uncertain"}
            try:
                if observe() and observed["after_head"] == observed["before_head"]:
                    observed["status"] = "failed_without_durable_change"
                    restore(counter=False)
            except Exception:
                pass
            raise
        observe()
        cid = view.get("candidate_id") if isinstance(view, dict) else None
        packed = self._query_learning_pack()
        if not (isinstance(packed, dict) and isinstance(packed.get("pending"), dict) and packed["gap"] is None
                and packed["pending"].get("decision_cid") == cid and observed["new_candidate_ids"] == [cid]):
            learning["query_draft_gap"] = {"code": "query_learning_gate_uncertain"}
            return self._result(self._hold("learning_control_invalid", text, ("learning_control_invalid",)))
        observed.update(status="completed", view_candidate_id=cid)
        if view.get("accepted") is True:
            return self._result(self._hold("learning_accepted_resubmit_required", pending["text"],
                                           ("learning_accepted_resubmit_required",)))
        return self._result(self._hold("learning_rejected", text, ("learning_rejected",)))

    def teach(self, payload, *, turn_id=None, replaces=None, expression_kind="fact"):
        if type(expression_kind) is not str or expression_kind not in ("fact", "query"):
            raise ValueError("invalid_expression_kind")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        if replaces is not None:
            _text("replaces", replaces)
        if turn_id is not None:
            _text("turn_id", turn_id)
        if expression_kind == "query":
            if self._recorder is None:
                return self._teach(payload, turn_id, replaces, expression_kind=expression_kind)
            text = self._action_text("teach", payload=payload, turn_id=turn_id, replaces=replaces,
                                     expression_kind=expression_kind)
            return self._traced(text, lambda: self._teach(payload, turn_id, replaces,
                                                          expression_kind=expression_kind),
                                "teach", memory=True)
        if self._recorder is None:
            return self._teach(payload, turn_id, replaces)
        text = self._action_text("teach", payload=payload, turn_id=turn_id, replaces=replaces)
        return self._traced(text, lambda: self._teach(payload, turn_id, replaces), "teach", memory=True)

    _LESSON_SOURCE_KEYS = ("text", "text_sha256", "conversation_id", "turn_id", "observation_id",
                           "input_event_id", "provenance_status", "model_binding")

    def _learning_payload(self, draft):
        """Pure contract check of a stage-2 lesson draft; no side effects, no parsing."""
        def fail(reason, detail):
            raise ValueError("%s: %s" % (reason, detail))

        if not isinstance(draft, dict):
            fail("learning_control_invalid", "draft must be a dict")
        try:
            draft = _json(draft)
        except (TypeError, ValueError):
            fail("learning_control_invalid", "draft must be finite JSON")
        for key in ("target", "ref", "positive", "negative", "approve"):
            if key not in draft:
                fail("learning_need_%s" % key, "missing %s" % key)
        binding = self._model_binding()
        allowed = set(self._LESSON_SOURCE_KEYS)

        def check_source(name, source, reason, allow_turn_none=False):
            if not isinstance(source, dict):
                fail(reason, "%s source must be a dict" % name)
            unknown = set(source) - allowed
            if unknown:
                fail("learning_control_invalid", "%s source has unknown keys %s" % (name, sorted(unknown)))
            for key in self._LESSON_SOURCE_KEYS:
                if key not in source:
                    fail(reason, "%s source missing %s" % (name, key))
            text = source.get("text")
            if not isinstance(text, str) or not text.strip():
                fail(reason, "%s source text must be nonempty" % name)
            if source.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
                fail("learning_control_invalid", "%s source text_sha256 mismatch" % name)
            for key in ("conversation_id", "observation_id", "input_event_id", "provenance_status"):
                if source.get(key) is not None and not isinstance(source[key], str):
                    fail("learning_control_invalid", "%s source %s must be text or null" % (name, key))
            if source.get("turn_id") is not None and not isinstance(source["turn_id"], str):
                fail("learning_control_invalid", "%s source turn_id must be text or null" % name)
            if not allow_turn_none and source.get("turn_id") is None and source.get("provenance_status") is None:
                fail("learning_control_invalid", "%s source needs turn_id or provenance_status" % name)
            if source.get("model_binding") != binding:
                fail("learning_model_changed", "%s source model_binding differs from current binding" % name)
            return source

        def check_record(name, rec, kind, required, reason):
            if not isinstance(rec, dict):
                fail(reason, "%s must be a record" % name)
            if set(rec) != {"kind", "fields", "evidence", "source"}:
                fail("learning_control_invalid", "%s record keys must be kind/fields/evidence/source" % name)
            if rec.get("kind") != kind:
                fail("learning_control_invalid", "%s kind must be %r" % (name, kind))
            fields = rec.get("fields")
            if not isinstance(fields, dict) or set(fields) != set(required):
                fail(reason, "%s fields must be exactly %s" % (name, sorted(required)))
            for f in required:
                if not isinstance(fields[f], str) or not fields[f].strip():
                    fail(reason, "%s fields.%s must be nonempty text" % (name, f))
            source = check_source(name, rec.get("source"), reason, allow_turn_none=(kind == "approve"))
            evidence = rec.get("evidence")
            if not isinstance(evidence, dict):
                fail(reason, "%s evidence must be a dict" % name)
            if evidence.get("source") != source["text"]:
                fail("learning_control_invalid", "%s evidence.source must equal source.text" % name)
            return rec

        raw_target = draft["target"]
        if not isinstance(raw_target, dict):
            fail("learning_need_target", "target must be a source capsule")
        target = {k: raw_target.get(k) for k in self._LESSON_SOURCE_KEYS if k in raw_target}
        check_source("target", target, "learning_need_target")

        ref = check_record("ref", draft["ref"], "equivalence", ("expression", "reference"), "learning_need_ref")
        if ref["fields"]["expression"] != target["text"]:
            fail("learning_control_invalid", "ref.fields.expression must equal target.text")

        positives = draft["positive"]
        negatives = draft["negative"]
        if not isinstance(positives, list):
            fail("learning_need_positive", "positive must be a list")
        if not isinstance(negatives, list):
            fail("learning_need_negative", "negative must be a list")
        positives = [check_record("positive[%d]" % i, rec, "positive", ("expression", "reference"),
                                  "learning_need_positive") for i, rec in enumerate(positives)]
        negatives = [check_record("negative[%d]" % i, rec, "unrecognized", ("expression",),
                                  "learning_need_negative") for i, rec in enumerate(negatives)]
        if not positives:
            fail("learning_need_positive", "at least one positive example required")
        if not negatives:
            fail("learning_need_negative", "at least one negative example required")
        limit = getattr(self.memory, "validation_limit", 16)
        if len(positives) + len(negatives) > limit:
            fail("learning_budget_exceeded", "validation exceeds limit %d" % limit)

        approve = check_record("approve", draft["approve"], "approve", (), "learning_need_approve")

        validation = [{"id": "positive_%d" % (i + 1), "text": rec["fields"]["expression"],
                       "equivalent": rec["fields"]["reference"]} for i, rec in enumerate(positives)]
        validation += [{"id": "negative_%d" % (i + 1), "text": rec["fields"]["expression"],
                        "unrecognized": True} for i, rec in enumerate(negatives)]
        payload = {"text": target["text"], "equivalent": ref["fields"]["reference"], "validation": validation}
        lesson = {"target": target, "ref": ref, "positive": positives, "negative": negatives, "approve": approve}
        try:
            encoded = json.dumps({"payload": payload,
                                  "provenance": {"conversation_id": self.conversation_id, "turn_id": None,
                                                 "lesson": lesson}},
                                 ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            fail("learning_control_invalid", "lesson is not finite JSON")
        bytes_limit = getattr(self.memory, "payload_bytes_limit", 32768)
        if len(encoded) > bytes_limit:
            fail("learning_budget_exceeded", "payload and provenance exceed %d bytes" % bytes_limit)
        return _json({"payload": payload, "lesson": lesson})

    def _teach(self, payload, turn_id, replaces, *, lesson=None, outcome=None, expression_kind="fact"):
        if type(expression_kind) is not str or expression_kind not in ("fact", "query"):
            raise ValueError("invalid_expression_kind")
        with self._guard():
            self.turn_counter += 1
            turn_id = _text("turn_id", turn_id) if turn_id is not None else "turn_%d" % self.turn_counter
            snapshot = self.context.snapshot()
            provenance = {"conversation_id": self.conversation_id, "turn_id": turn_id}
            if lesson is not None:
                try:
                    lesson = _json(lesson)
                except (TypeError, ValueError):
                    raise ValueError("learning_control_invalid: lesson must be finite JSON")
                if not isinstance(lesson, dict) or not isinstance(lesson.get("approve"), dict) \
                        or not isinstance(lesson["approve"].get("source"), dict):
                    raise ValueError("learning_control_invalid: lesson approve source missing")
                # Stamp only after the actual counter increment / turn_id selection above.
                lesson["approve"]["source"]["conversation_id"] = self.conversation_id
                lesson["approve"]["source"]["turn_id"] = turn_id
                provenance["lesson"] = lesson
            if self._active is not None:
                self._active["operation_kind"] = "teach"
            if expression_kind == "query":
                view = self.memory.teach(payload, provenance, replaces=replaces,
                                         expression_kind=expression_kind)
            else:
                view = self.memory.teach(payload, provenance, replaces=replaces)
            if self._active is not None:
                # This gate actually ran before the rehydrate and the independent session
                # save. Keep its report even if either of those fails; it does not imply
                # delivery or rule use.
                self._active["operation_result"] = _json({**view, "memory_revision": self._revision(),
                                                          "conversation_id": self.conversation_id})
            if view.get("accepted"):
                self._rehydrate(snapshot)
            if outcome is not None:
                try:
                    # passive outcome metadata from the actual view/stamped lesson, before the sole save
                    cid = view.get("candidate_id")
                    if not isinstance(cid, str) or not cid.strip():
                        raise ValueError("candidate_id unavailable")
                    final_ok = view.get("accepted") is True
                    approve = copy.deepcopy(lesson["approve"])
                    head = self._binding()
                    head = {"seq": head["seq"], "change_id": head["change_id"]}
                    sig = None if final_ok else outcome["signature"]
                    for held in (outcome["pending"], outcome["candidate"]):
                        held["decision_cid"] = cid
                        held["decision_head"] = dict(head)
                    outcome["pending"]["accepted"] = final_ok
                    outcome["candidate"]["approve"] = approve
                    outcome["candidate"]["last_attempt_signature"] = sig
                    if expression_kind == "query":
                        self._learning["query_draft_gap"] = None
                except Exception:
                    if expression_kind == "query":
                        self._learning["query_draft_gap"] = {"code": "query_learning_outcome_failed"}
                    else:
                        self._learning_gap = {"code": "collection_failed"}
            self._save_memory_change()
            return {**view, "memory_revision": self._revision(), "conversation_id": self.conversation_id}

    def retract(self, candidate_id, reason):
        _text("candidate_id", candidate_id)
        _text("reason", reason)
        if self._recorder is None:
            return self._retract(candidate_id, reason)
        text = self._action_text("retract", candidate_id=candidate_id, reason=reason)
        return self._traced(text, lambda: self._retract(candidate_id, reason), "retract", memory=True)

    def _retract(self, candidate_id, reason):
        with self._guard():
            snapshot = self.context.snapshot()
            view = self.memory.retract(candidate_id, reason)
            if self._active is not None:
                # Retraction already ran before the rehydrate and the session save. Keep
                # its report even if either of those fails.
                self._active["operation_result"] = _json({**view, "memory_revision": self._revision(),
                                                          "conversation_id": self.conversation_id})
            self._rehydrate(snapshot)
            self._save_memory_change()
            return {**view, "memory_revision": self._revision(), "conversation_id": self.conversation_id}

    def research(self, query):
        _text("query", query)
        if self._recorder is None:
            return self._research(query)
        return self._traced(self._action_text("research", query=query), lambda: self._research(query), "research")

    def _research(self, query):
        with self._guard():
            if self.research_hook is None:
                return {"status": "unavailable", "trusted": False, "verified": False,
                        "reason": "no_research_hook", "query": query}
            report = _json(self.research_hook(query))
            if not isinstance(report, dict):
                report = {"result": report}
            report.update(verified=False, trusted=False)
            for field in ("observations", "claims", "sources"):
                for item in report.get(field) or []:
                    if isinstance(item, dict):
                        item.update(trusted=False, verified=False)
            search = report.get("search") if isinstance(report.get("search"), dict) else {}
            error = report.get("error") or search.get("error")
            status = ("failed" if search.get("status") == "failed" or error else
                      report.get("status") or report.get("evidence_status") or "observed")
            return {"status": status, "trusted": False, "verified": False, "query": query,
                    "report": report, "evidence_status": report.get("evidence_status"),
                    "error": error, "memory_revision": self._revision(),
                    "conversation_id": self.conversation_id}

    def _collection_gap_env(self, code):
        return {"protocol": "marco-learning-collection-v1", "gap": {"code": code}}

    def _collection_pack(self, limit, conversation_id, model_binding, memory_binding, turn_counter,
                         targets, draft, gap):
        # pure: detached finite Session-v2 envelope built ONLY from already captured facts
        try:
            env = {"protocol": "marco-learning-collection-v1", "conversation_id": conversation_id,
                   "model_binding": model_binding, "memory_binding": memory_binding,
                   "turn_counter": turn_counter, "targets": targets, "draft": draft, "gap": gap}
            blob = json.dumps(env, ensure_ascii=False, allow_nan=False, sort_keys=True,
                              separators=(",", ":"))
            if (not isinstance(limit, int) or isinstance(limit, bool)
                    or len(blob.encode("utf-8")) > limit):
                return self._collection_gap_env("collection_oversize")
            return json.loads(blob)
        except Exception:
            return self._collection_gap_env("collection_unserializable")

    def _collection_check(self, env, state, model_binding, revision, limit, vlimit, views):
        # pure validation of a saved envelope against caller-supplied current facts; returns
        # (targets, draft) detached copies or raises ValueError
        proto = "marco-learning-collection-v1"
        bad = ValueError("collection_invalid")

        def nb(v):
            return isinstance(v, str) and v.strip() != ""

        def isid(v):
            return v is None or nb(v)

        def sint(v):
            return type(v) is int and v >= 0

        def h64(v):
            return isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)

        def memb(m):
            if not isinstance(m, dict) or set(m) != {"seq", "change_id"} or not sint(m["seq"]):
                return False
            return m["change_id"] is None if m["seq"] == 0 else nb(m["change_id"])

        def fullbind(b):
            base = {"content_fingerprint", "effective_key", "parser_sha256"}
            if isinstance(b, dict) and set(b) == base | {"graph_member_path", "graph_member_sha256", "knowledge_binding"}:
                if not (nb(b["graph_member_path"]) and h64(b["graph_member_sha256"]) and h64(b["knowledge_binding"])):
                    return False
            elif not (isinstance(b, dict) and set(b) == base):
                return False
            return h64(b["content_fingerprint"]) and h64(b["parser_sha256"]) and nb(b["effective_key"])

        def gapok(g):
            return (isinstance(g, dict) and set(g) == {"code"} and nb(g["code"]) and len(g["code"]) <= 128)

        def turnok(t, allow_none=False):
            if t is None:
                return allow_none
            n = t[5:] if isinstance(t, str) and t.startswith("turn_") else ""
            return (n.isascii() and n.isdigit() and not n.startswith("0") and 0 < int(n)
                    and int(n) <= env["turn_counter"])

        def srcok(s, allow_none=False):
            return (isinstance(s, dict) and set(s) == set(self._LESSON_SOURCE_KEYS)
                    and nb(s["text"])
                    and s["text_sha256"] == hashlib.sha256(s["text"].encode("utf-8")).hexdigest()
                    and s["conversation_id"] == env["conversation_id"]
                    and s["model_binding"] == model_binding
                    and turnok(s["turn_id"], allow_none)
                    and s["observation_id"] is None and s["input_event_id"] is None
                    and s["provenance_status"] == "partial")

        def spanok(sp, src):
            return (isinstance(sp, dict) and set(sp) == {"start", "end", "text"}
                    and type(sp["start"]) is int and type(sp["end"]) is int
                    and 0 <= sp["start"] < sp["end"] <= len(src)
                    and isinstance(sp["text"], str) and sp["text"] != ""
                    and src[sp["start"]:sp["end"]] == sp["text"])

        def recok(r, kind, allow_none_turn=False):
            if (not isinstance(r, dict) or set(r) != {"kind", "fields", "evidence", "source"}
                    or r["kind"] != kind or not srcok(r["source"], allow_none_turn)):
                return False
            f, ev, src = r["fields"], r["evidence"], r["source"]["text"]
            if not isinstance(f, dict):
                return False
            if kind == "approve":
                roles = set()
                if f != {}:
                    return False
            elif kind == "unrecognized":
                roles = {"expression"}
            else:
                roles = {"expression", "reference"}
            if kind != "approve" and (set(f) != roles or any(not nb(f[k]) for k in roles)):
                return False
            if kind == "equivalence" and f["expression"] != pending["text"]:
                return False
            ekeys = {"source", "start", "end", "capture_spans", "fixed_spans", "coverage_status",
                     "declaration_source", "declaration_sha256", "model_binding", "binding_status",
                     "binding_reason", "form_id"}
            if (not isinstance(ev, dict) or set(ev) != ekeys or ev["source"] != src
                    or type(ev["start"]) is not int or ev["start"] != 0
                    or type(ev["end"]) is not int or ev["end"] != len(src)
                    or ev["coverage_status"] != "complete"
                    or ev["declaration_source"] != "parser.data.learning_dialogue"
                    or not h64(ev["declaration_sha256"]) or not nb(ev["form_id"])
                    or ev["model_binding"] is not None
                    or ev["binding_status"] != "partial"
                    or ev["binding_reason"] != "parser_model_binding_unavailable"):
                return False
            caps, fixed = ev["capture_spans"], ev["fixed_spans"]
            if not isinstance(caps, dict) or set(caps) != roles or not isinstance(fixed, list):
                return False
            spans = []
            for k in roles:
                if not spanok(caps[k], src) or caps[k]["text"] != f[k]:
                    return False
                spans.append(caps[k])
            for sp in fixed:
                if not spanok(sp, src):
                    return False
                spans.append(sp)
            pos_ = 0
            for sp in sorted(spans, key=lambda s: s["start"]):
                if sp["start"] != pos_:
                    return False
                pos_ = sp["end"]
            return pos_ == len(src)

        keys = {"protocol", "conversation_id", "model_binding", "memory_binding", "turn_counter",
                "targets", "draft", "gap"}
        if not isinstance(env, dict) or env.get("protocol") != proto or set(env) not in (keys, {"protocol", "gap"}):
            raise bad
        blob = json.dumps(env, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        if (type(limit) is not int or limit <= 0 or len(blob.encode("utf-8")) > limit
                or json.loads(blob) != env):
            raise bad
        if set(env) == {"protocol", "gap"}:
            if not gapok(env["gap"]):
                raise bad
            return {}, None
        if (env["conversation_id"] != state.get("conversation_id")
                or env["model_binding"] != model_binding or state.get("model_binding") != model_binding
                or env["memory_binding"] != state.get("memory_binding")
                or not _nonneg(env["turn_counter"]) or env["turn_counter"] != state.get("turn_counter")
                or state.get("memory_revision") != revision):
            raise bad
        gap = env["gap"]
        if gap is not None and not gapok(gap):
            raise bad
        if (not fullbind(model_binding) or type(env["turn_counter"]) is not int
                or isinstance(revision, bool)
                or not isinstance(env["memory_binding"], dict) or not memb(env["memory_binding"])):
            raise bad
        targets, draft = env["targets"], env["draft"]
        if not isinstance(targets, dict) or not set(targets) <= {"pending"}:
            raise bad
        pending = targets.get("pending")
        if pending is None:
            if draft is not None:
                raise bad
            return {}, None
        pkeys = set(self._LESSON_SOURCE_KEYS) | {"initial_observation_ids", "accepted"}
        if (not isinstance(pending, dict)
                or not pkeys <= set(pending) <= pkeys | {"decision_cid", "decision_head"}):
            raise bad
        if (not srcok({k: pending[k] for k in self._LESSON_SOURCE_KEYS})
                or type(pending["accepted"]) is not bool
                or not isid(pending.get("decision_cid"))
                or not (pending.get("decision_head") is None or memb(pending.get("decision_head")))):
            raise bad
        ids = pending["initial_observation_ids"]
        if (not isinstance(ids, list) or len(ids) > 128 or any(not nb(i) for i in ids)
                or len(set(ids)) != len(ids)):
            raise bad
        cid = pending.get("decision_cid")
        sig = None
        if draft is not None:
            dkeys = {"target", "ref", "positive", "negative", "approve", "last_attempt_signature"}
            if (not isinstance(draft, dict)
                    or not dkeys <= set(draft) <= dkeys | {"decision_cid", "decision_head"}
                    or not (draft.get("decision_head") is None or memb(draft.get("decision_head")))):
                raise bad
            if draft["target"] != {k: pending[k] for k in self._LESSON_SOURCE_KEYS}:
                raise bad
            pos, neg = draft["positive"], draft["negative"]
            if not isinstance(pos, list) or not isinstance(neg, list):
                raise bad
            if type(vlimit) is not int or vlimit <= 0 or len(pos) + len(neg) > vlimit:
                raise bad
            if ((draft["ref"] is not None and not recok(draft["ref"], "equivalence"))
                    or (draft["approve"] is not None and not recok(draft["approve"], "approve", True))
                    or any(not recok(r, "positive") for r in pos)
                    or any(not recok(r, "unrecognized") for r in neg)):
                raise bad
            sig = draft["last_attempt_signature"]
            if (sig is not None and not h64(sig)) or not isid(draft.get("decision_cid")):
                raise bad
            cid = draft.get("decision_cid") or cid
        if pending["accepted"] is True or sig is not None:
            # accepted/rejected markers are resumed only on an exact actual CID witness
            missing = ValueError("collection_witness_missing")
            want = pending["accepted"] is True
            if (not isinstance(cid, str) or not cid or draft is None
                    or (want and sig is not None) or (not want and not h64(sig))):
                raise missing
            head = pending.get("decision_head")
            if (pending.get("decision_cid") != cid or draft.get("decision_cid") != cid
                    or not isinstance(head, dict) or set(head) != {"seq", "change_id"}
                    or draft.get("decision_head") != head
                    or type(head["seq"]) is not int or head["seq"] != revision
                    or head != env["memory_binding"]):
                raise missing
            if views is None:
                raise ValueError("witness_required")
            matches = [v for v in views if isinstance(v, dict) and v.get("candidate_id") == cid]
            if len(matches) != 1:
                raise missing
            view = matches[0]
            report = view.get("report")
            payload = view.get("payload")
            prov = view.get("provenance")
            if (view.get("kind") != "expression" or view.get("schema") != "marco-learning-memory-v1"
                    or view.get("supervision") != "explicit_user_teaching"
                    or type(view.get("revision")) is not int or view["revision"] != head["seq"]
                    or not isinstance(report, dict) or type(report.get("accepted")) is not bool
                    or type(view.get("gate_accepted")) is not bool
                    or view["gate_accepted"] is not report["accepted"]
                    or view.get("accepted") is not want
                    or view.get("status") != ("active" if want else "rejected")
                    or (want and report["accepted"] is not True)
                    or not isinstance(payload, dict) or not isinstance(prov, dict)):
                raise missing
            lesson = prov.get("lesson")
            try:
                target, ref, appr = draft["target"], draft["ref"], draft["approve"]
                pos, neg = draft["positive"], draft["negative"]
                if (not isinstance(lesson, dict) or not pos or not neg or ref is None or appr is None
                        or set(lesson) != {"target", "ref", "positive", "negative", "approve"}
                        or any(json.dumps(lesson[k], sort_keys=True, allow_nan=False)
                               != json.dumps(draft[k], sort_keys=True, allow_nan=False)
                               for k in lesson)):
                    raise missing
                reference = ref["fields"]["reference"]
                want_payload = {
                    "text": target["text"],
                    "equivalent": reference,
                    "validation": (
                        [{"id": "positive_%d" % (i + 1), "text": e["fields"]["expression"],
                          "equivalent": e["fields"]["reference"]}
                         for i, e in enumerate(pos)]
                        + [{"id": "negative_%d" % (i + 1), "text": e["fields"]["expression"],
                            "unrecognized": True}
                           for i, e in enumerate(neg)]),
                }
                src = appr["source"]
                tid = src["turn_id"]
                if (json.dumps(payload, sort_keys=True, allow_nan=False)
                        != json.dumps(want_payload, sort_keys=True, allow_nan=False)
                        or set(prov) != {"conversation_id", "turn_id", "lesson"}
                        or prov["conversation_id"] != env["conversation_id"]
                        or src["conversation_id"] != env["conversation_id"]
                        or not isinstance(tid, str) or prov["turn_id"] != tid
                        or not tid.startswith("turn_") or not tid[5:].isascii()
                        or not tid[5:].isdigit() or str(int(tid[5:])) != tid[5:]
                        or int(tid[5:]) > env["turn_counter"]):
                    raise missing
                if not want:
                    body = json.dumps(
                        {"payload": payload, "selected_binding": model_binding,
                         "memory_before_head": [head["seq"], head["change_id"]]},
                        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                        allow_nan=False).encode("utf-8")
                    if hashlib.sha256(body).hexdigest() != sig:
                        raise missing
                json.dumps([payload, prov, report], allow_nan=False)
            except ValueError:
                raise
            except Exception:
                raise missing from None
        elif (pending.get("decision_cid") is not None or pending.get("decision_head") is not None
                or (draft is not None and (draft.get("decision_cid") is not None
                                           or draft.get("decision_head") is not None))):
            raise ValueError("collection_witness_missing")
        return _json(targets), _json(draft)

    def snapshot(self):
        state = {"schema": SCHEMA, "language": self.language, "conversation_id": self.conversation_id,
                 "base_sha256": self.base_sha256, "memory_revision": self._revision(),
                 "memory_binding": self._binding(), "model_binding": self._model_binding(),
                 "context": self._checkpoint_snapshot(),
                 "turn_counter": self.turn_counter}
        if self._learning_enabled:
            try:
                state["learning_collection"] = self._collection_pack(
                    getattr(self.memory, "payload_bytes_limit", None), state["conversation_id"],
                    state["model_binding"], state["memory_binding"], state["turn_counter"],
                    self._learning.get("targets"), self._learning.get("draft"), self._learning_gap)
            except Exception:
                # optional passive metadata only; native state stays authoritative
                state["learning_collection"] = self._collection_gap_env("collection_failed")
        if self._learning_enabled:
            packed = self._query_source_pack()
            if packed is not None:
                state["query_learning_source"] = packed
        if self._learning_enabled:
            packed = self._query_learning_pack()
            if packed is not None:
                state["query_learning_draft"] = packed
        if self._selected is not None:
            state["selected_graph_turns"] = self._native_turns
            if self._native_history_gap is not None:
                state["selected_graph_gap"] = self._native_history_gap
        return _json(state)

    def _checkpoint_snapshot(self):
        """Context snapshot that also refreshes the session-owned rollback checkpoint.

        The checkpoint is the last *accepted* context snapshot (verified aggregate replay included),
        kept independently of the disposable replay cache.  It is a rollback point, not a second
        reading ledger: it is only ever produced by ``context.snapshot()`` itself."""
        snapshot = self.context.snapshot()
        self._checkpoint = copy.deepcopy(snapshot)
        return snapshot

    def save(self):
        try:
            self._save_state()
        except BaseException as error:
            self._note_save("failed", type(error).__name__)
            raise
        self._note_save("completed" if self.state_path else "skipped")

    def _note_save(self, outcome, detail=None):
        if self._active is not None:
            self._active["saves"].append({"outcome": outcome, "detail": detail})

    def _save_state(self):
        if not self.state_path:
            return
        data = json.dumps(self.snapshot(), allow_nan=False, sort_keys=True)
        directory = os.path.dirname(os.path.abspath(self.state_path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.state_path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # --- optional trace (explicit caller-owned ledger only) ---------------------------------

    @staticmethod
    def _action_text(action, **fields):
        return json.dumps({"action": action, **fields}, sort_keys=True, ensure_ascii=False, allow_nan=False)

    def _trace_stamp(self):
        """Actual selected model and encoder configuration; the realizer is untracked and stays unknown."""
        stamp = {"model": {"content_fingerprint": self.model.content_fingerprint,
                           "effective_key": self.model.effective_key}}
        encoder = getattr(self.model, "encoder", None)
        if encoder is not None:
            fields = {name: getattr(encoder, name, None) for name in (
                "mode", "dimensions", "jamo_weight", "smoothing", "route_thresh", "cluster_thresh",
                "goal_sim_thresh", "device")}
            stamp["encoder"] = {"reference": str(getattr(encoder, "model_name", "") or "") or None,
                                "declaration_digest": hashlib.sha256(json.dumps(
                                    fields, sort_keys=True, default=str).encode("utf-8")).hexdigest()}
        return stamp

    @staticmethod
    def _evidence_turns(value, out):
        if isinstance(value, dict):
            evidence = value.get("evidence")
            if isinstance(evidence, dict) and type(evidence.get("turn")) is int and evidence["turn"] >= 0:
                out.add(evidence["turn"])
            for item in value.values():
                DialogueSession._evidence_turns(item, out)
        elif isinstance(value, (list, tuple)):
            for item in value:
                DialogueSession._evidence_turns(item, out)

    def _answer_learning_dependencies(self, result):
        """Private partial capsule: archived selected expressions behind the proof leaf of an ordinary answer."""
        from marco.language.entry_origins import validated_entry_origin
        capsule = {"schema": "marco-answer-learning-dependencies-v1",
                   "scope": "known_selected_archived_fact_premises", "status": "partial",
                   "basis": "result_proof_leaf_and_archived_selection_with_recorded_acceptance",
                   "items": [], "gaps": []}
        gaps = capsule["gaps"]

        def gap(code, path=None, oid=None, rev=None, clause=None):
            if len(gaps) < 64:
                gaps.append({"proof_path": path, "observation_id": oid, "reading_revision": rev,
                             "clause_ordinal": clause, "code": code})

        def strict(value):
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0

        meaning = result.get("meaning") if isinstance(result, dict) else None
        query = meaning.get("query") if isinstance(meaning, dict) else None
        transitions = result.get("transitions") if isinstance(result, dict) else None
        if (not isinstance(meaning, dict) or meaning.get("act") != "inform" or "kind" in meaning
                or result.get("status") != "answered" or not isinstance(transitions, list)
                or not isinstance(query, list) or len(query) != 3
                or not all(isinstance(x, str) for x in query)):
            gap("unsupported_answer_scope")
            return capsule
        by_fact = {}
        for position, row in enumerate(transitions):
            if isinstance(row, dict) and "operation" not in row and isinstance(row.get("fact"), list):
                try:
                    by_fact.setdefault(tuple(row["fact"]), []).append((position, row))
                except TypeError:
                    continue
        roots = by_fact.get(tuple(query), [])
        if len(roots) != 1:
            gap("answer_root_uncollected")
            return capsule
        leaves, seen = [], set()

        def walk(position, row, active):
            if position in active:
                gap("proof_cycle", ["transitions", position])
                return
            if position in seen:
                return
            seen.add(position)
            if any(key in row for key in ("operation", "part", "action_event", "hypothesis")):
                gap("unsupported_proof_row", ["transitions", position])
            elif "rule" in row or "parents" in row:
                parents = row.get("parents")
                if not isinstance(parents, list) or not parents:
                    gap("proof_parent_malformed", ["transitions", position])
                    return
                for parent in parents:
                    try:
                        found = by_fact.get(tuple(parent), [])
                    except TypeError:
                        found = []
                    if len(found) != 1:
                        gap("proof_parent_unresolved", ["transitions", position])
                        continue
                    walk(found[0][0], found[0][1], active | {position})
            elif isinstance(row.get("evidence"), dict):
                leaves.append((position, row))
            else:
                gap("unsupported_proof_row", ["transitions", position])

        walk(roots[0][0], roots[0][1], frozenset())
        from marco.trace.runtime import plain_json, TraceContractError
        context = getattr(self, "context", None)
        ledger = getattr(context, "reading_ledger", None)
        observation_ids = getattr(context, "observation_ids", None)
        base_sha256 = getattr(self, "base_sha256", None)
        fingerprint = getattr(self, "_knowledge_binding", None)

        def valid_oid(value):
            return (isinstance(value, str) and len(value) >= 2 and value[0] == "o" and value[1] != "0"
                    and all(c in "0123456789" for c in value[1:]))

        def int_list(value, bound):
            return (isinstance(value, list) and all(strict(x) and x < bound for x in value)
                    and len(set(value)) == len(value))

        selected = []
        for position, row in leaves:
            path = ["transitions", position]
            evidence = row["evidence"]
            source = evidence.get("source")
            oid, rev = getattr(source, "oid", None), getattr(source, "rev", None)
            turn = evidence.get("turn")
            if not valid_oid(oid) or not strict(rev) or rev < 1 or not strict(turn):
                gap("reading_identity_unknown", path)
                continue
            try:
                turn_ok = observation_ids[turn] == oid
            except Exception:
                turn_ok = False
            if not turn_ok:
                gap("reading_identity_unknown", path)
                continue
            try:
                entry = ledger.get(oid) if ledger is not None else None
                versions = entry.get("versions") if isinstance(entry, dict) else None
                record = versions[rev - 1] if isinstance(versions, list) and rev <= len(versions) else None
            except Exception:
                record = None
            if not isinstance(record, dict) or record.get("observation_id") != oid \
                    or not strict(record.get("reading_revision")) or record["reading_revision"] < 1 \
                    or record.get("reading_revision") != rev or record.get("source") != str(source):
                gap("reading_record_unavailable", path, oid, rev)
                continue
            if not isinstance(base_sha256, str) or record.get("parser_base_sha256") != base_sha256:
                gap("parser_base_foreign", path, oid, rev)
                continue
            if record.get("reason") in ("correction", "referent_resolution"):
                gap("correction_unknown" if record.get("reason") == "correction"
                    else "referent_resolution_unknown", path, oid, rev)
                continue
            start, end, text = evidence.get("start"), evidence.get("end"), evidence.get("text")
            if not strict(start) or not strict(end) or end <= start or not isinstance(text, str):
                gap("evidence_span_invalid", path, oid, rev)
                continue
            parsed = record.get("parsed")
            facts = parsed.get("facts") if isinstance(parsed, dict) else None
            query_list = parsed.get("query") if isinstance(parsed, dict) else None
            query_len = len(query_list) if isinstance(query_list, list) else 0
            archive = parsed.get("entry_selection") if isinstance(parsed, dict) else None
            if not isinstance(facts, list) or not isinstance(archive, dict) \
                    or set(archive) != {"schema", "scope", "status", "coordinate_space", "items", "gaps"} \
                    or archive["schema"] != "marco-entry-selection-v1" \
                    or archive["scope"] != "known_selected_input_clauses" or archive["status"] != "partial" \
                    or archive["coordinate_space"] != "parser_view" \
                    or not isinstance(archive["items"], list) or not isinstance(archive["gaps"], list):
                gap("archived_selection_unavailable", path, oid, rev)
                continue
            ordinals = []
            for ordinal, fact in enumerate(facts):
                ev = fact.get("evidence") if isinstance(fact, dict) else None
                if isinstance(ev, dict) and isinstance(fact.get("triple"), (list, tuple)) \
                        and list(fact["triple"]) == row["fact"] \
                        and strict(ev.get("start")) and strict(ev.get("end")) \
                        and ev.get("start") == start and ev.get("end") == end and ev.get("text") == text:
                    ordinals.append(ordinal)
            if len(ordinals) != 1:
                gap("fact_ordinal_ambiguous" if ordinals else "fact_ordinal_unmatched", path, oid, rev)
                continue
            items_ok = True
            for item in archive["items"]:
                span = item.get("span") if isinstance(item, dict) else None
                targets = item.get("targets") if isinstance(item, dict) else None
                if not isinstance(item, dict) or set(item) != {"clause_ordinal", "span", "compiler_index",
                                                               "origin", "targets", "derivation"} \
                        or not strict(item["clause_ordinal"]) \
                        or not (item["compiler_index"] is None or strict(item["compiler_index"])) \
                        or not isinstance(span, list) or len(span) != 2 \
                        or not all(strict(x) for x in span) or span[0] > span[1] \
                        or not isinstance(targets, dict) or set(targets) != {"facts", "query"} \
                        or not int_list(targets["facts"], len(facts)) \
                        or not int_list(targets["query"], query_len):
                    items_ok = False
                    break
            if not items_ok:
                gap("archived_selection_malformed", path, oid, rev)
                continue
            matches = [item for item in archive["items"] if ordinals[0] in item["targets"]["facts"]]
            if len(matches) != 1:
                gap("archived_selection_unavailable", path, oid, rev)
                continue
            item = matches[0]
            clause = item["clause_ordinal"]
            if item["span"] != [start, end]:
                gap("selection_span_mismatch", path, oid, rev, clause)
                continue
            if item["compiler_index"] is None:
                gap("compiler_index_unknown", path, oid, rev, clause)
                continue
            gaps_ok, blocked = True, False
            for g in archive["gaps"]:
                if not isinstance(g, dict) or set(g) != {"clause_ordinal", "code"} \
                        or not (g["clause_ordinal"] is None or strict(g["clause_ordinal"])) \
                        or not isinstance(g["code"], str) or not g["code"].strip():
                    gaps_ok = False
                    break
                if g["clause_ordinal"] is None or g["clause_ordinal"] == clause:
                    blocked = True
            if not gaps_ok:
                gap("archived_gap_malformed", path, oid, rev, clause)
                continue
            if blocked:
                gap("archived_selection_gap_unknown", path, oid, rev, clause)
                continue
            try:
                item = plain_json(item)
                if len(json.dumps(item, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"), allow_nan=False).encode("utf-8")) > 8192:
                    gap("selection_metadata_oversize", path, oid, rev, clause)
                    continue
            except (TraceContractError, ValueError, TypeError, RecursionError):
                gap("selection_metadata_invalid", path, oid, rev, clause)
                continue
            try:
                origin = validated_entry_origin(item.get("origin"))
            except ValueError:
                gap("origin_invalid", path, oid, rev, clause)
                continue
            if origin is None:
                gap("origin_unknown", path, oid, rev, clause)
                continue
            if origin["graph_binding"] is None:
                gap("binding_unknown", path, oid, rev, clause)
                continue
            if not isinstance(fingerprint, str) or origin["graph_binding"] != fingerprint:
                gap("foreign_origin", path, oid, rev, clause)
                continue
            selected.append((path, oid, rev, ordinals[0], item, origin, record))
        if not selected:
            return capsule
        # Unsigned local records are reported history only, not cryptographic or world truth.
        try:
            views = self.memory.candidates()
        except Exception:
            views = None
        if not isinstance(views, list):
            for path, oid, rev, _o, item, _g, _r in selected:
                gap("origin_confirmation_unavailable", path, oid, rev, item.get("clause_ordinal"))
            return capsule
        body_keys = ("schema", "kind", "payload", "annotation", "provenance", "report",
                     "supervision", "replaces")

        def finite(value):
            try:
                raw = json.dumps(value, allow_nan=False, sort_keys=True, ensure_ascii=False)
                return len(raw.encode("utf-8")) <= 8192
            except Exception:
                return False

        def same(a, b):
            try:
                return (json.dumps(a, allow_nan=False, sort_keys=True)
                        == json.dumps(b, allow_nan=False, sort_keys=True))
            except Exception:
                return False

        def nonblank(value):
            return isinstance(value, str) and bool(value.strip())

        def confirm(origin, record):
            cid = origin["candidate_id"]
            rule_id = origin["rule_id"]
            teaching = origin["teaching"]
            found = [v for v in views if isinstance(v, dict) and v.get("candidate_id") == cid]
            if (len(found) != 1 or found[0].get("accepted") is not True
                    or found[0].get("gate_accepted") is not True):
                return False
            view = found[0]
            if any(k not in view for k in body_keys):
                return False
            body = {k: view[k] for k in body_keys}
            if not finite(body):
                return False
            prov, report = body["provenance"], body["report"]
            if (body["schema"] != "marco-learning-memory-v1" or body["kind"] != "expression"
                    or body["supervision"] != "explicit_user_teaching"
                    or not isinstance(body["payload"], dict)
                    or not isinstance(body["annotation"], dict)
                    or not isinstance(prov, dict) or not isinstance(report, dict)
                    or report.get("accepted") is not True
                    or not nonblank(prov.get("conversation_id")) or not nonblank(prov.get("turn_id"))
                    or prov.get("conversation_id") != teaching["conversation_id"]
                    or prov.get("turn_id") != teaching["turn_id"]):
                return False
            history = view.get("history")
            if not isinstance(history, list):
                return False
            rule_rows = []
            for h in history:
                if not isinstance(h, dict):
                    return False
                if h.get("target_kind") != "rule" or h.get("target_id") != rule_id:
                    continue
                seq, ordv = h.get("seq"), h.get("ord")
                if not strict(seq) or seq <= 0 or not strict(ordv):
                    return False
                rule_rows.append(h)
            matches = []
            for h in rule_rows:
                ev, ap = h.get("evidence"), h.get("approval")
                if (h.get("op") == "ADD_RULE" and h.get("change_id") == origin["accepted_change_id"]
                        and isinstance(ev, dict) and ev.get("candidate_id") == cid
                        and ev.get("rule_id") == rule_id and ev.get("kind") == "expression"
                        and ev.get("operation") in ("teach", "replace")
                        and isinstance(ap, dict) and ap.get("candidate_id") == cid
                        and ap.get("by") == "learning-memory"):
                    matches.append(h)
            if len(matches) != 1:
                return False
            row = matches[0]
            hrev = row.get("revision")
            if not strict(hrev) or hrev + 1 != origin["rule_revision"]:
                return False
            pl = row.get("payload")
            hbody = pl.get("body") if isinstance(pl, dict) else None
            if (not isinstance(hbody, dict) or set(hbody) != set(body_keys)
                    or not finite(hbody) or not same(hbody, body)):
                return False
            ev_report, validation = row["evidence"].get("report"), row.get("validation")
            if (not isinstance(ev_report, dict) or not finite(ev_report)
                    or not same(ev_report, report)
                    or not isinstance(validation, dict) or not finite(validation)
                    or not same(validation, report)):
                return False
            head = record.get("installed_memory_head")
            if not strict(head) or row["seq"] > head:
                return False
            prior = [h for h in rule_rows if h["seq"] <= head]
            latest = max(prior, key=lambda h: (h["seq"], h["ord"]))
            if latest is not row:
                return False
            keys = [(h["seq"], h["ord"]) for h in prior]
            return len(keys) == len(set(keys))

        for path, oid, rev, ordinal, item, origin, record in selected:
            clause = item.get("clause_ordinal")
            try:
                confirmed = confirm(origin, record) is True
            except Exception:
                confirmed = False
            if not confirmed:
                gap("acceptance_confirmation_unknown", path, oid, rev, clause)
                continue
            capsule["items"].append({
                "proof_path": path, "observation_id": oid, "reading_revision": rev,
                "fact_ordinal": ordinal, "clause_ordinal": clause,
                "parser_span": copy.deepcopy(item.get("span")),
                "compiler_index": item.get("compiler_index"), "origin": origin,
                "source_scope": "archived_selected_input_expression",
                "confirmation": "historical_acceptance_recorded", "original_source_span": None})
        return capsule

    def _used_readings(self, result):
        """Archived premise slots named by the result's own transition/proof evidence indexes; None if unknown.

        Nothing is reparsed or rematched, and installed readings the result does not cite are not listed."""
        try:
            if not isinstance(result, dict):
                return None
            turns = set()
            self._evidence_turns(result.get("transitions"), turns)
            self._evidence_turns(result.get("proof"), turns)
            self._evidence_turns((result.get("verification") or {}).get("proof"), turns)
            if not turns:
                return None
            context = self.context.snapshot()
            ids, records, rows = context["observation_ids"], context["reading_ledger"]["records"], []
            for index in sorted(turns):
                if index >= len(ids):
                    return None
                entry = records[ids[index]]
                version = entry["versions"][entry["active"] - 1]
                seq = version["installed_memory_head"]
                head = {"seq": seq, "change_id": None}
                if seq > 0:
                    head["change_id"] = self.memory._store.change(seq)["change_id"]
                row = {"observation_id": ids[index], "reading_revision": version["reading_revision"],
                       "source": version["source"], "model_content_fingerprint": self.model.content_fingerprint,
                       "memory_head": head}
                if version.get("parser_grammar_sha256") is not None:
                    row["parser_grammar_sha256"] = version["parser_grammar_sha256"]
                rows.append(row)
            return rows
        except Exception:     # noqa: BLE001 -- unknown usage stays unknown
            return None

    @staticmethod
    def _criterion(checks, gate=None):
        if gate is not None:
            return {"id": "learning_memory_gate_report", "scope": {"finite_gate_report": gate}}
        names = []
        for check in checks:
            name = next((check[key] for key in ("id", "check", "name", "reason", "kind")
                         if isinstance(check.get(key), str) and check[key]), None)
            if name is not None and name not in names:
                names.append(name)
        if checks:
            return {"id": "engine_verification_checks", "scope": {"engine_returned_criteria": names}}
        return None

    def _traced(self, text, execute, kind, *, memory=False):
        """Durable input -> execute -> deferred honest reports; the semantic method never sees the trace sink."""
        recorder = self._recorder
        self.last_trace = None
        with self._guard():
            head = self._binding()
            attempt = recorder.begin(text, provenance={"installed_memory_head": head})
        active = self._active = {"saves": [], "computed": None, "operation_result": None, "used": None,
                                 "trace_attempt": attempt, "trace_recorder": recorder, "trace_kind": kind}
        result = error = None
        try:
            result = execute()
        except BaseException as caught:     # noqa: BLE001 -- reported below, then re-raised unchanged
            error = caught
        finally:
            self._active = None
        after = self._binding() if not self._closed else head
        try:
            self._report(attempt, kind, active, result, error, head, after, memory)
        except BaseException as trace_failure:     # noqa: BLE001
            if error is not None:
                raise error from trace_failure
            trace_failure.executed_result = result      # committed, but its record is missing
            note = getattr(trace_failure, "add_note", None)
            if callable(note):
                note("Operation completed before trace finalization failed; inspect separate persistence reports.")
            raise
        if error is not None:
            raise error
        return result

    def _report(self, attempt, kind, active, result, error, head, after, memory):
        recorder = self._recorder
        computed = active["computed"] if active["computed"] is not None else (
            result if kind == "respond" and error is None else None)
        inner_teach = kind == "respond" and active.get("operation_kind") == "teach"
        operation_result = result if error is None else active["operation_result"]
        if inner_teach and active.get("operation_result") is not None:
            operation_result = active["operation_result"]
        details = {"action": kind}
        if inner_teach:
            details["operation_kind"] = "teach"
        if error is not None:
            details["error"] = type(error).__name__
        if (kind in ("teach", "retract") or inner_teach) and isinstance(operation_result, dict):
            details.update(accepted=operation_result.get("accepted"),
                           candidate_id=operation_result.get("candidate_id"), status=operation_result.get("status"))
        elif kind == "research" and isinstance(result, dict):
            details.update(status=result.get("status"), trusted=False, verified=False)
        recorder.mark_persistence(attempt, "runtime_action", "failed" if error is not None else "completed",
                                  _json(details))
        if memory or inner_teach:
            recorder.mark_persistence(attempt, "learning_memory_commit",
                                      "committed" if after != head else "unchanged",
                                      {"before_head": head, "after_head": after,
                                       "scope": "accepted_overlay_head_change"})
        for save in active["saves"]:
            recorder.mark_persistence(attempt, "session_state_save", save["outcome"], {"detail": save["detail"]})
        checks = []
        if isinstance(computed, dict) and isinstance(computed.get("verification"), dict):
            checks = [c for c in computed["verification"].get("checks") or [] if isinstance(c, dict)]
        gate = None
        if (kind == "teach" or inner_teach) and isinstance(operation_result, dict) \
                and isinstance(operation_result.get("report"), dict):
            try:
                gate = _json(operation_result["report"])
            except (TypeError, ValueError):
                gate = None
            if gate is not None and type(gate.get("accepted")) is bool:
                # A finite admission decision from this teaching execution, not an
                # invented semantic/world-truth check or a replay of an old report.
                checks = [{"ok": gate["accepted"], "reason": gate.get("reason"), "detail": gate}]
        envelope = computed
        if kind != "respond" and operation_result is not None:
            envelope = {"status": "observed", "operator": "runtime_action",
                        "answer": json.dumps(operation_result, ensure_ascii=False, sort_keys=True, allow_nan=False),
                        "verification": {"checks": checks}}
        elif inner_teach:
            # Trace-only detached copy of the selected public message; the delivered
            # result is never mutated and never replaced by the admission gate.
            source = result if error is None and isinstance(result, dict) else (
                computed if isinstance(computed, dict) else None)
            detached = None
            if source is not None:
                try:
                    detached = _json(source)
                except (TypeError, ValueError):
                    detached = None
            if isinstance(detached, dict):
                verification = detached.get("verification")
                verification = dict(verification) if isinstance(verification, dict) else {}
                verification["checks"] = checks
                detached["verification"] = verification
                envelope = detached
            else:
                envelope = {"verification": {"checks": checks}}
        declared = {"installed_memory_head": head}
        if active["used"] is not None:
            declared["used_readings"] = active["used"]
        if kind == "respond" and error is None and isinstance(active.get("_relation_usage"), dict) \
                and isinstance(result, dict) and isinstance(result.get("relation_attempt"), dict) \
                and result["relation_attempt"].get("status") in ("conditional", "meaning_question"):
            usage = active["_relation_usage"]
            for section in ("assumptions", "rules", "sources", "composition"):
                if isinstance(usage.get(section), list):
                    declared[section] = usage[section]
        if kind == "respond" and error is None and isinstance(result, dict) \
                and result.get("status") == "answered" and isinstance(active.get("learning_dependencies"), dict):
            declared["learning_dependencies"] = active["learning_dependencies"]
        if kind == "respond" and error is None and isinstance(result, dict) \
                and result.get("status") == "answered" and isinstance(active.get("query_learning_dependencies"), dict):
            declared["query_learning_dependencies"] = active["query_learning_dependencies"]
        if kind == "respond" and error is None and isinstance(result, dict) \
                and result.get("status") == "answered" and not inner_teach \
                and active.get("selected_native_route") is None:
            rows = []
            try:
                from marco.language.entry_origins import validated_entry_origin
                binding = self._knowledge_binding
                seen = set()
                visits = 0
                size = 2
                sources = (
                    ("learning_dependencies", "marco-answer-learning-dependencies-v1",
                     "known_selected_archived_fact_premises",
                     "result_proof_leaf_and_archived_selection_with_recorded_acceptance", True),
                    ("query_learning_dependencies", "marco-answer-query-learning-dependencies-v1",
                     "known_selected_current_query_expression",
                     "current_native_selection_and_recorded_acceptance", False))
                for key, schema, scope, basis, fact in sources:
                    cap = active.get(key)
                    if not isinstance(cap, dict) or cap.get("schema") != schema \
                            or cap.get("scope") != scope or cap.get("status") != "partial" \
                            or cap.get("basis") != basis:
                        continue
                    cap_items = cap.get("items")
                    if not isinstance(cap_items, list) or not isinstance(cap.get("gaps"), list):
                        continue
                    if len(cap_items) > 32768:
                        raise OverflowError("projection work")
                    visits += len(cap_items)
                    if visits > 65536:
                        raise OverflowError("projection work")
                    for item in cap_items:
                        if not isinstance(item, dict) \
                                or item.get("confirmation") != "historical_acceptance_recorded":
                            continue
                        if fact and item.get("source_scope") != "archived_selected_input_expression":
                            continue
                        try:
                            origin = validated_entry_origin(item.get("origin"))
                        except (ValueError, TypeError):
                            continue
                        if origin is None or not isinstance(binding, str) \
                                or origin["graph_binding"] != binding:
                            continue
                        teaching = origin["teaching"]
                        row = {"candidate_id": origin["candidate_id"], "rule_id": origin["rule_id"],
                               "rule_revision": origin["rule_revision"],
                               "accepted_change_id": origin["accepted_change_id"],
                               "teaching": {"conversation_id": teaching["conversation_id"],
                                            "turn_id": teaching["turn_id"]}}
                        identity = (row["candidate_id"], row["rule_id"], row["rule_revision"],
                                    row["accepted_change_id"], teaching["conversation_id"],
                                    teaching["turn_id"], origin["graph_binding"])
                        if identity in seen:
                            continue
                        size += len(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                               separators=(",", ":"), allow_nan=False).encode("utf-8")) \
                            + (1 if rows else 0)
                        if size > 131072:
                            raise OverflowError("projection bytes")
                        seen.add(identity)
                        rows.append(row)
            except Exception:
                rows = []
            declared["used_learning"] = rows
            declared["partial_sections"] = ["used_learning"]
        criterion =self._criterion(checks, gate)
        if criterion is not None:
            declared["criterion"] = criterion
        native_turn = kind == "respond" and active.get("selected_native_route") is not None
        if native_turn:
            declared["selected_native_judgement"] = _json(active.get("selected_native_judgement"))
            declared["selected_native_route"] = _json(active["selected_native_route"])
        flush = (lambda ledger, input_id, trace_id: self.context.flush_trace(ledger, input_id)) \
            if kind == "respond" and not native_turn else None
        if error is not None:
            failed_save = any(save["outcome"] == "failed" for save in active["saves"])
            if flush is not None:
                # The accepted recorder discovers already-written descendants of
                # this input. Flush once so error output retains the actual routing.
                flush(recorder.ledger, attempt.input_id, attempt.trace_id)
            recorder._record_failure(attempt, envelope, error, "save" if failed_save else "execution", declared)
            self.last_trace = {"status": "error", "attempt_id": attempt.attempt_id, "turn": attempt.turn,
                               "error_type": type(error).__name__}
            return
        envelope = result if kind == "respond" and not inner_teach else envelope
        summary = recorder.finish(attempt, envelope, provenance=declared, pending_flush=flush)
        self.last_trace = {"status": "recorded", "attempt_id": attempt.attempt_id, "turn": attempt.turn,
                           "summary": summary}

    # --- internals -------------------------------------------------------------------

    def _revision(self):
        return max((c["revision"] for c in self.memory.candidates()), default=0)

    def _hold(self, reason, said, keys):
        """A hold whose ask comes only from the selected parser's ``context_replies``; with no declared
        reply the answer is None and the structured reason is the clarification metadata."""
        parser = getattr(self.context, "_parser_instance", None)
        replies = (getattr(parser, "data", None) or {}).get("context_replies") or {}
        answer = None
        for key in keys:
            template = replies.get(key)
            if isinstance(template, str) and template.strip():
                try:
                    answer = template.format(**{"말": said})
                except (KeyError, IndexError, ValueError):
                    continue
                break
        return {"meaning": {"act": "hold", "reason": reason, "said": said}, "answer": answer}

    def _save_memory_change(self):
        try:
            self.save()
        except OSError as error:
            self._persistence_failed = True
            raise SessionPersistenceError("Learning memory committed, but session state save failed. "
                                          "Reopen the session before continuing.") from error

    def _conditional_relation(self, text, result, out, before, native, *, unknown_question=False):
        if unknown_question is True:
            return self._conditional_relation_query(text, result, out, before, native)
        if native is not None or type(self.model) is not pack_model.PackModel or self._active is None \
                or not isinstance(out, dict) or out.get("status") != "unresolved":
            return out
        meaning = out.get("meaning")
        if not isinstance(meaning, dict) or meaning.get("act") != "hold":
            return out
        parser0 = getattr(self.context, "_parser_instance", None)
        data0 = getattr(parser0, "data", None)
        replies0 = data0.get("context_replies") if isinstance(data0, dict) else None
        keys = ("relation_conditional", "relation_meaning_question")
        if not isinstance(replies0, dict):
            return out
        present = [k in replies0 for k in keys]
        if not any(present):
            return out
        reason = str(meaning.get("reason") or out.get("reason") or "")
        from marco.reasoning.context import gap_class
        if gap_class(reason)[0] in ("routing", "conflict") or reason == "historical_reading_unavailable" \
                or reason.startswith("program"):
            return out
        import hashlib as _hl
        from relational_semantics import substitute

        def stop(code, stage):
            raise ValueError(code, stage)

        def digest(value):
            return _hl.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                         allow_nan=False).encode("utf-8")).hexdigest()

        def rows(snap_or_list):
            if not isinstance(snap_or_list, (list, tuple)):
                stop("unread_invalid", "target")
            limit = getattr(self.context, "max_turns", None)
            if type(limit) is not int or len(snap_or_list) > min(limit, 128):
                stop("unread_overflow", "target")
            found = {}
            for row in list(snap_or_list):
                if not isinstance(row, dict):
                    continue
                t, at = row.get("text"), row.get("at")
                if not isinstance(t, str) or not t.strip() or type(at) is not int or at < 0:
                    continue
                if row.get("범용"):
                    continue
                if (t, at) in found:
                    found[(t, at)] = None
                else:
                    found[(t, at)] = True
            return found

        try:
            if not all(present):
                stop("capability_partial", "opt_in")
            prior = rows(before.get("unread") if isinstance(before, dict) else None)
            current = rows(getattr(self.context, "unread", None))
            eligible = [k for k, v in prior.items()
                        if v is True and current.get(k) is True and k[0] != text]
            targets = self._learning.get("targets") if isinstance(self._learning, dict) else None
            pending = targets.get("pending") if isinstance(targets, dict) else None
            if pending is not None:
                if (not isinstance(pending, dict) or pending.get("accepted") is not False
                        or not isinstance(pending.get("text"), str)
                        or pending.get("text_sha256") != _hl.sha256(pending["text"].encode("utf-8")).hexdigest()
                        or pending.get("conversation_id") != self.conversation_id
                        or pending.get("model_binding") != self._model_binding()):
                    stop("target_pending_invalid", "target")
                eligible = [k for k in eligible if k[0] == pending["text"]]
            if len(eligible) != 1:
                stop("target_ambiguous" if eligible else "target_missing", "target")
            target_text, target_at = eligible[0]
            from marco.runtime.relation_attempt import _prepare_relation_attempt_owned
            from marco.reasoning.relation_hypotheses import evaluate_relation_hypotheses, _valid_json
            acq = _prepare_relation_attempt_owned(self, text, unread_text=target_text, unread_at=target_at,
                                                  active=self._active)
            if not isinstance(acq, dict) or acq.get("status") != "ready" or acq.get("gaps"):
                stop("acquisition_gap", "acquisition")
            projection, qrec = acq["projection"], acq["query_record"]
            parser = acq["parser"]
            hyp = projection.get("relation_hypotheses") if isinstance(projection, dict) else None
            if not hyp:
                stop("hypotheses_missing", "projection")
            preplies = parser.data.get("context_replies")
            if not isinstance(preplies, dict) or any(preplies.get(k) != replies0.get(k) for k in keys) \
                    or any(not isinstance(preplies.get(k), str) for k in keys):
                stop("reply_mismatch", "projection")
            rsources = projection.get("reply_sources")
            if not isinstance(rsources, dict) or any(k not in rsources for k in keys):
                stop("reply_sources_missing", "projection")
            ev = evaluate_relation_hypotheses(parser, acq["context_snapshot"], acq["proposal"], qrec,
                                              projection=projection, binding=acq["binding"])
            if not isinstance(ev, dict) or ev.get("gaps"):
                stop("evaluation_gap", "evaluation")
            base = ev.get("baseline")
            if not isinstance(base, dict) or base.get("complete") is not True or base.get("matches"):
                stop("baseline_incomplete", "evaluation")
            outcomes = ev.get("outcomes")
            if not isinstance(outcomes, list) or not outcomes:
                stop("outcomes_missing", "evaluation")
            supported = []
            for oc in outcomes:
                world = oc.get("conditional") if isinstance(oc, dict) else None
                if not isinstance(world, dict) or world.get("complete") is not True:
                    stop("alternative_incomplete", "evaluation")
                if oc.get("conflicts") or len(world.get("matches") or ()) != 1:
                    continue
                match = world["matches"][0]
                use = self._relation_proof_use(acq, oc, match)
                if use.get("own_hypothesis"):
                    supported.append((oc, match, use))
            mq = False
            if not supported:
                sole = outcomes[0] if len(outcomes) == 1 else None
                sworld = sole.get("conditional") if isinstance(sole, dict) else None
                if not isinstance(sworld, dict) or sworld.get("complete") is not True \
                        or sworld.get("matches") != [] or sole.get("conflicts") != []:
                    stop("no_supported_outcome", "evaluation")
                mq = True
                oc, match, use = sole, None, None
            else:
                if len(supported) > 1:
                    stop("conditional_ambiguous", "evaluation")
                oc, match, use = supported[0]
            cand = oc["assumption"]["candidate"]
            virtual = cand["transformation"]["virtual_source"]
            first = ""
            if not mq:
                rendered = substitute(qrec["parsed"]["query"][0], {k[1:]: v for k, v in match["bindings"].items()})
                if not isinstance(rendered, dict):
                    stop("render_invalid", "render")
                rendered["triple"] = list(match["triple"])
                if rendered["triple"] != list(match["triple"]) or not isinstance(rendered.get("render"), list) \
                        or any(not isinstance(p, str) for p in rendered["render"]):
                    stop("render_invalid", "render")
                answer = "".join(rendered["render"])
                first = replies0[keys[0]].format(assumption=virtual, answer=answer)
            second = replies0[keys[1]].format(expression=target_text, reference=virtual)
            source_echo = {"text": target_text, "at": target_at,
                           "unknown_span": copy.deepcopy(cand.get("unknown_span"))}
            selected_ids = [] if mq else list(match["support_ids"])
            assumptions = []
            for other in outcomes:
                c = other["assumption"]["candidate"]
                row = {"mode": "counterfactual", "confirmed": False, "candidate_id": other["candidate_id"],
                       "source": target_text, "unknown_span": copy.deepcopy(c.get("unknown_span")),
                       "transformation": copy.deepcopy(c.get("transformation")),
                       "frame_source_ref": copy.deepcopy(c.get("source_ref")),
                       "policy_source": copy.deepcopy(c.get("policy_source")),
                       "selected_for_delivery": other is oc}
                if other is oc and not mq:
                    row["support_paths"] = copy.deepcopy(use["paths"])
                    row["support_ids"] = selected_ids
                    row["support_bundles"] = copy.deepcopy(use["used_bundle_rows"])
                assumptions.append(row)
            rules = []
            for item in ([] if mq else use["rules"]):
                rules.append({"id": item["id"], "version": copy.deepcopy(item["version"]),
                              "declaration_digest": digest(item["declaration"]),
                              "digest_scope": "captured native parser.data.rules object"})
            sources = [{"source_id": oc["assumption"]["premise_id"], "observation_id": None,
                        "reading_revision": None, "text": target_text, "span": None,
                        "unknown_span": source_echo["unknown_span"]}]
            snapshot = acq.get("context_snapshot")
            ledger = snapshot.get("reading_ledger") if isinstance(snapshot, dict) else None
            records = ledger.get("records") if isinstance(ledger, dict) else None
            for prem in ([] if mq else use["premises"]):
                if prem["premise_id"] == oc["assumption"]["premise_id"]:
                    continue
                ref = prem.get("source_ref") if isinstance(prem.get("source_ref"), dict) else {}
                oid, rev = ref.get("observation_id"), ref.get("reading_revision")
                stext = None
                if isinstance(records, dict) and isinstance(oid, str) and type(rev) is int and rev >= 1:
                    entry = records.get(oid)
                    versions = entry.get("versions") if isinstance(entry, dict) else None
                    record = versions[rev - 1] if isinstance(versions, list) and rev <= len(versions) else None
                    if isinstance(record, dict) and record.get("observation_id") == oid \
                            and record.get("reading_revision") == rev and isinstance(record.get("source"), str):
                        stext = record["source"]
                fact = prem.get("original_fact") if isinstance(prem.get("original_fact"), dict) else {}
                ev_ = fact.get("evidence") if isinstance(fact.get("evidence"), dict) else {}
                start, end, etext = ev_.get("start"), ev_.get("end"), ev_.get("text")
                span = [start, end] if (stext is not None and type(start) is int and type(end) is int
                                         and 0 <= start <= end <= len(stext) and isinstance(etext, str)
                                         and stext[start:end] == etext) else None
                sources.append({"source_id": prem["premise_id"], "observation_id": oid if isinstance(oid, str) else None,
                                "reading_revision": rev if type(rev) is int else None, "text": stext,
                                "span": span})
            qref = qrec.get("source_ref") if isinstance(qrec.get("source_ref"), dict) else {}
            composition = [{"reference": "query", "annotation_sha256": qref.get("annotation_sha256"),
                            "declaration_digest": qref.get("annotation_sha256"),
                            "index": qref.get("index"), "graph_source": copy.deepcopy(qref.get("graph_source"))},
                           {"reference": "frame", "annotation_sha256": (cand.get("source_ref") or {}).get("annotation_sha256")
                            if isinstance(cand.get("source_ref"), dict) else None,
                            "declaration_digest": (cand.get("source_ref") or {}).get("annotation_sha256")
                            if isinstance(cand.get("source_ref"), dict) else None,
                            "source_ref": copy.deepcopy(cand.get("source_ref"))},
                           {"reference": "policy", "declaration_digest": digest(cand.get("policy_source")),
                            "digest_scope": "selected candidate policy_source capsule",
                            "policy_source": copy.deepcopy(cand.get("policy_source"))}]
            for k in ((keys[1],) if mq else keys):
                composition.append({"reference": k, "declaration_digest": digest({"template": preplies[k],
                                                                                "graph_source": rsources[k]}),
                                    "digest_scope": "{template,graph_source} reply declaration",
                                    "template": preplies[k], "graph_source": copy.deepcopy(rsources[k])})
            cands_all = [copy.deepcopy(o["assumption"]["candidate"]) for o in outcomes]
            attempt = {"schema": "marco-relation-dialogue-v1", "status": "meaning_question" if mq else "conditional",
                       "source": source_echo, "binding": copy.deepcopy(acq["binding"]),
                       "query": copy.deepcopy(qrec), "proposal": copy.deepcopy(acq["proposal"]),
                       "evaluation": copy.deepcopy(ev),
                       "selected": {"candidate_id": oc["candidate_id"], "match": copy.deepcopy(match),
                                    "support_ids": selected_ids},
                       "projection_fingerprint": projection.get("fingerprint"),
                       "witness": copy.deepcopy(acq.get("witness")), "gaps": []}
            final = copy.deepcopy(out)
            final["status"] = "unresolved"
            final["transitions"] = []
            final["meaning"] = {"act": "hold", "reason": "relation_meaning_pending", "said": target_text}
            final["answer"] = first + second
            final["relation_attempt"] = attempt
            usage = {"assumptions": assumptions, "rules": rules, "sources": sources, "composition": composition}
            if not _valid_json(final, byte_limit=1048576) or not cands_all \
                    or not _valid_json(usage, byte_limit=262144):
                stop("result_invalid", "validation")
            if isinstance(self._active, dict) and final.get("status") == "unresolved" \
                    and final["relation_attempt"].get("status") in ("conditional", "meaning_question"):
                self._active["_relation_usage"] = usage
            return final
        except Exception as exc:
            args = exc.args if isinstance(exc, ValueError) and len(exc.args) == 2 else ("driver_failed", "driver")
            code, stage = (str(a)[:128] for a in args)
            failed = copy.deepcopy(out)
            failed["relation_attempt"] = {"schema": "marco-relation-dialogue-v1", "status": "gap",
                                          "gaps": [{"code": code, "stage": stage}]}
            return failed

    def _conditional_relation_query(self, text, result, out, before, native):
        if native is not None or type(self.model) is not pack_model.PackModel or self._active is None \
                or not isinstance(out, dict) or out.get("status") != "unresolved":
            return out
        meaning = out.get("meaning")
        if not isinstance(meaning, dict) or meaning.get("act") != "hold":
            return out
        parser0 = getattr(self.context, "_parser_instance", None)
        data0 = getattr(parser0, "data", None)
        replies0 = data0.get("context_replies") if isinstance(data0, dict) else None
        keys = ("relation_conditional", "relation_meaning_question")
        if not isinstance(replies0, dict):
            return out
        present = [k in replies0 for k in keys]
        if not any(present):
            return out
        reason = str(meaning.get("reason") or out.get("reason") or "")
        from marco.reasoning.context import gap_class
        if gap_class(reason)[0] in ("routing", "conflict") or reason == "historical_reading_unavailable" \
                or reason.startswith("program"):
            return out
        import hashlib as _hl
        from relational_semantics import substitute
        schema = "marco-relation-query-dialogue-v1"

        def stop(code, stage):
            raise ValueError(code, stage)

        def digest(value):
            return _hl.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                         allow_nan=False).encode("utf-8")).hexdigest()

        def rows(snap_or_list):
            if not isinstance(snap_or_list, (list, tuple)):
                stop("unread_invalid", "target")
            limit = getattr(self.context, "max_turns", None)
            if type(limit) is not int or len(snap_or_list) > min(limit, 128):
                stop("unread_overflow", "target")
            found = {}
            for row in list(snap_or_list):
                if not isinstance(row, dict):
                    continue
                t, at = row.get("text"), row.get("at")
                if not isinstance(t, str) or not t.strip() or type(at) is not int or at < 0:
                    continue
                if row.get("범용"):
                    continue
                if (t, at) in found:
                    found[(t, at)] = None
                else:
                    found[(t, at)] = True
            return found

        local = []

        def gap(code, stage, reading_id=None, candidate_id=None, group_id=None):
            if len(local) >= 32:
                stop("driver_gap_limit", "selection")
            local.append({"code": code, "stage": stage, "reading_id": reading_id,
                          "candidate_id": candidate_id, "group_id": group_id})

        try:
            if not all(present):
                stop("capability_partial", "opt_in")
            if self.context._permitted(None) is not True:
                return out
            cached = getattr(self.model, "_language_projection", None)
            if not isinstance(cached, dict) or cached.get("schema") != "graph-dialogue-projection-v1":
                return out
            if not isinstance(cached.get("provenance"), dict):
                stop("projection_provenance_invalid", "projection")
            declared = cached.get("relation_hypothesis_queries")
            if not declared:
                return out
            if not isinstance(declared, list) or any(not isinstance(r, dict) for r in declared):
                stop("association_declaration_invalid", "opt_in")
            prior = rows(before.get("unread") if isinstance(before, dict) else None)
            current = rows(getattr(self.context, "unread", None))
            eligible = [k for k, v in prior.items()
                        if v is True and current.get(k) is True and k[0] != text]
            targets = self._learning.get("targets") if isinstance(self._learning, dict) else None
            pending = targets.get("pending") if isinstance(targets, dict) else None
            if pending is not None:
                if (not isinstance(pending, dict) or pending.get("accepted") is not False
                        or not isinstance(pending.get("text"), str)
                        or pending.get("text_sha256") != _hl.sha256(pending["text"].encode("utf-8")).hexdigest()
                        or pending.get("conversation_id") != self.conversation_id
                        or pending.get("model_binding") != self._model_binding()):
                    stop("target_pending_invalid", "target")
                eligible = [k for k in eligible if k[0] == pending["text"]]
            if len(eligible) != 1:
                stop("target_ambiguous" if eligible else "target_missing", "target")
            target_text, target_at = eligible[0]
            trace_attempt = self._active.get("trace_attempt")
            input_id = getattr(trace_attempt, "input_id", None)
            if not isinstance(input_id, str) or not input_id:
                stop("owner_invalid", "ownership")
            from marco.runtime.relation_attempt import _prepare_relation_attempt_owned
            from marco.reasoning.relation_hypotheses import _valid_json, _canonical
            from marco.reasoning.relation_query_hypotheses import evaluate_relation_query_hypotheses
            acq = _prepare_relation_attempt_owned(self, text, unread_text=target_text, unread_at=target_at,
                                                  active=self._active, unknown_question=True)
            if not isinstance(acq, dict) or acq.get("schema") != "marco-relation-query-attempt-acquisition-v1" \
                    or acq.get("status") != "ready" or acq.get("gaps"):
                stop("acquisition_gap", "acquisition")
            projection, parser = acq["projection"], acq["parser"]
            proposal, qprop = acq["proposal"], acq["query_proposal"]
            if not isinstance(projection, dict) or not isinstance(proposal, dict) or not isinstance(qprop, dict) \
                    or not isinstance(qprop.get("readings"), list):
                stop("acquisition_invalid", "acquisition")
            preplies = parser.data.get("context_replies")
            if not isinstance(preplies, dict) or any(preplies.get(k) != replies0.get(k) for k in keys) \
                    or any(not isinstance(preplies.get(k), str) for k in keys):
                stop("reply_mismatch", "projection")
            rsources = projection.get("reply_sources")
            if not isinstance(rsources, dict) or any(k not in rsources for k in keys):
                stop("reply_sources_missing", "projection")
            ev = evaluate_relation_query_hypotheses(parser, acq["context_snapshot"], proposal, qprop,
                                                    projection=projection, binding=acq["binding"])
            if not isinstance(ev, dict) or set(ev) != {"schema", "binding", "source", "considered_candidates",
                                                       "query_proposal", "groups", "reading_refs", "gaps"} \
                    or ev["schema"] != "relation-query-hypothesis-evaluation-v1" \
                    or not all(isinstance(ev[k], list) for k in ("groups", "reading_refs", "gaps")):
                stop("evaluation_invalid", "evaluation")
            if not ev["groups"] and not ev["reading_refs"] and ev["gaps"]:
                stop("evaluation_refused", "evaluation")
            readings = qprop["readings"]
            echo = ev["query_proposal"]
            if not isinstance(echo, dict) or _canonical(echo.get("readings")) != _canonical(readings):
                stop("evaluation_incoherent", "evaluation")
            groups = {}
            for g in ev["groups"]:
                if not isinstance(g, dict) or not isinstance(g.get("id"), str) or g["id"] in groups \
                        or "query_record" not in g:
                    stop("evaluation_incoherent", "evaluation")
                groups[g["id"]] = g
            refs = {}
            for r in ev["reading_refs"]:
                if not isinstance(r, dict) or not isinstance(r.get("reading_id"), str) \
                        or r["reading_id"] in refs:
                    stop("evaluation_incoherent", "evaluation")
                refs[r["reading_id"]] = r
            by_reading = {}
            for rd in readings:
                if not isinstance(rd, dict) or not isinstance(rd.get("id"), str) or rd["id"] in by_reading:
                    stop("evaluation_incoherent", "evaluation")
                by_reading[rd["id"]] = rd
            if set(refs) != set(by_reading) or len(refs) != len(ev["reading_refs"]):
                stop("evaluation_incoherent", "evaluation")
            cand_rows = proposal.get("candidates")
            if not isinstance(cand_rows, list) or any(not isinstance(c, dict) or not isinstance(c.get("id"), str)
                                                      for c in cand_rows):
                stop("proposal_invalid", "acquisition")
            cands = {}
            for c in cand_rows:
                if c["id"] in cands:
                    stop("proposal_invalid", "acquisition")
                cands[c["id"]] = c

            assoc_rows = projection.get("relation_hypothesis_queries")
            if not isinstance(assoc_rows, list) or any(not isinstance(r, dict) for r in assoc_rows):
                stop("association_declaration_invalid", "projection")
            coord_keys = ("policy_index", "frame_index", "query_index")
            row_keys = coord_keys + ("query_ref", "predicate", "known_slot", "roles", "terminal",
                                     "association_source")

            def association_row(rd):
                coords = tuple(rd.get(k) for k in coord_keys)
                if any(type(c) is not int for c in coords):
                    return None
                hits = [r for r in assoc_rows
                        if all(type(r.get(k)) is int for k in coord_keys)
                        and tuple(r.get(k) for k in coord_keys) == coords]
                if len(hits) != 1 or any(k not in hits[0] for k in row_keys):
                    return None
                row = hits[0]
                if _canonical(row["query_ref"]) != _canonical(rd.get("query_ref")) \
                        or _canonical(row["association_source"]) != _canonical(rd.get("association_source")):
                    return None
                return row

            entries, delivery = [], {}
            for rd in readings:
                rid, cid = rd.get("id"), rd.get("candidate_id")
                ref = refs[rid]
                gid = ref.get("group_id")
                group = groups.get(gid)
                if group is None:
                    stop("evaluation_incoherent", "evaluation")
                cand = cands.get(cid)
                if cand is None or ref.get("candidate_id") != cid:
                    gap("candidate_missing", "selection", rid, cid, gid)
                    continue
                if _canonical(group["query_record"]) != _canonical(rd.get("virtual_record")):
                    gap("group_record_mismatch", "selection", rid, cid, gid)
                    continue
                association = association_row(rd)
                if association is None:
                    gap("association_row_unresolved", "selection", rid, cid, gid)
                    continue
                entry = {"reading": rd, "candidate": cand, "group_id": gid, "outcome_index": None,
                         "association": association}
                entries.append(entry)
                evaluation = group.get("evaluation")
                idx = ref.get("outcome_index")
                outcomes = evaluation.get("outcomes") if isinstance(evaluation, dict) else None
                if ref.get("status") != "mapped" or type(idx) is not int or not isinstance(outcomes, list) \
                        or not 0 <= idx < len(outcomes):
                    gap("candidate_unmapped", "evaluation", rid, cid, gid)
                    continue
                oc = outcomes[idx]
                if not isinstance(oc, dict) or oc.get("candidate_id") != cid \
                        or _canonical((oc.get("assumption") or {}).get("candidate")) != _canonical(cand):
                    gap("outcome_mismatch", "evaluation", rid, cid, gid)
                    continue
                entry["outcome_index"], entry["outcome"] = idx, oc
                base = evaluation.get("baseline")
                world = oc.get("conditional")
                if not isinstance(base, dict) or base.get("complete") is not True or base.get("matches"):
                    gap("baseline_unusable", "evaluation", rid, cid, gid)
                    continue
                if not isinstance(world, dict) or world.get("complete") is not True:
                    gap("alternative_incomplete", "evaluation", rid, cid, gid)
                    continue
                if oc.get("conflicts") or len(world.get("matches") or ()) != 1:
                    gap("no_unique_match", "evaluation", rid, cid, gid)
                    continue
                match = world["matches"][0]
                try:
                    use = self._relation_proof_use(acq, oc, match)
                except Exception as exc:
                    gap(str(exc.args[0])[:128] if isinstance(exc, ValueError) and len(exc.args) == 2
                        else "proof_failed", "proof", rid, cid, gid)
                    continue
                if not use.get("own_hypothesis"):
                    gap("proof_without_own_hypothesis", "proof", rid, cid, gid)
                    continue
                key = _canonical({"candidate": cand, "query_record": group["query_record"],
                                  "association": association, "match": match, "use": use})
                slot = delivery.setdefault(key, {"entries": [], "match": match, "use": use, "oc": oc})
                slot["entries"].append(entry)

            def reference_key(entry):
                return _canonical({"candidate": entry["candidate"],
                                   "query_record": entry["reading"].get("virtual_record"),
                                   "association": entry["association"]})

            classes = {}
            for entry in entries:
                classes.setdefault(reference_key(entry), []).append(entry)
            chosen = status = None
            if len(delivery) > 1:
                gap("conditional_ambiguous", "selection")
            elif len(delivery) == 1:
                chosen, status = next(iter(delivery.values())), "conditional"
            elif not readings:
                gap("query_reading_missing", "selection")
            elif not classes:
                gap("no_usable_reference", "selection")
            elif len(classes) > 1:
                gap("reference_ambiguous", "selection")
            else:
                chosen, status = {"entries": next(iter(classes.values())), "match": None, "use": None,
                                  "oc": None}, "meaning_question"

            snapshot = acq.get("context_snapshot")
            question = {"input_id": input_id, "text": text}
            final = copy.deepcopy(out)
            final["status"] = "unresolved"
            attempt = {"schema": schema, "status": "gap", "source": None, "binding": copy.deepcopy(acq["binding"]),
                       "query": None, "proposal": copy.deepcopy(proposal),
                       "query_proposal": copy.deepcopy(qprop), "evaluation": copy.deepcopy(ev),
                       "selected": None, "projection_fingerprint": projection.get("fingerprint"),
                       "witness": copy.deepcopy(acq.get("witness")), "gaps": local}
            if chosen is None:
                attempt["source"] = {"text": target_text, "at": target_at, "unknown_span": None,
                                     "question": question}
                final["relation_attempt"] = attempt
                if not _valid_json(final, byte_limit=1048576):
                    stop("result_invalid", "validation")
                return final

            final["transitions"] = []
            first_entry = chosen["entries"][0]
            cand, rd0 = first_entry["candidate"], first_entry["reading"]
            oc, match, use = chosen["oc"], chosen["match"], chosen["use"]
            virtual = cand["transformation"]["virtual_source"]
            second = replies0[keys[1]].format(expression=target_text, reference=virtual)
            answer = second
            if status == "conditional":
                rendered = substitute(rd0["virtual_record"]["parsed"]["query"][0],
                                      {k[1:]: v for k, v in match["bindings"].items()})
                if not isinstance(rendered, dict):
                    stop("render_invalid", "render")
                rendered["triple"] = list(match["triple"])
                if not isinstance(rendered.get("render"), list) \
                        or any(not isinstance(p, str) for p in rendered["render"]):
                    stop("render_invalid", "render")
                answer = replies0[keys[0]].format(assumption=virtual, answer="".join(rendered["render"])) + second
            source_echo = {"text": target_text, "at": target_at,
                           "unknown_span": copy.deepcopy(cand.get("unknown_span")), "question": question}
            selected_ids = list(match["support_ids"]) if match is not None else []
            reading_ids = [e["reading"]["id"] for e in chosen["entries"]]
            assumptions = []
            for c in cand_rows:
                row = {"mode": "counterfactual", "confirmed": False, "kind": "assertion_candidate",
                       "candidate_id": c["id"], "source": target_text,
                       "unknown_span": copy.deepcopy(c.get("unknown_span")),
                       "transformation": copy.deepcopy(c.get("transformation")),
                       "frame_source_ref": copy.deepcopy(c.get("source_ref")),
                       "policy_source": copy.deepcopy(c.get("policy_source")),
                       "selected_for_delivery": c["id"] == cand["id"]}
                if status == "conditional" and c["id"] == cand["id"]:
                    row["support_paths"] = copy.deepcopy(use["paths"])
                    row["support_ids"] = selected_ids
                    row["support_bundles"] = copy.deepcopy(use["used_bundle_rows"])
                assumptions.append(row)
            for rd in readings:
                assumptions.append({"mode": "counterfactual", "confirmed": False, "kind": "query_reading",
                                    "reading_id": rd.get("id"), "candidate_id": rd.get("candidate_id"),
                                    "policy_index": rd.get("policy_index"), "frame_index": rd.get("frame_index"),
                                    "query_index": rd.get("query_index"),
                                    "unknown_span": copy.deepcopy(rd.get("unknown_span")),
                                    "transformation": copy.deepcopy(rd.get("transformation")),
                                    "original_spans": copy.deepcopy(rd.get("original_spans")),
                                    "query_ref": copy.deepcopy(rd.get("query_ref")),
                                    "association_source": copy.deepcopy(rd.get("association_source")),
                                    "selected_for_delivery": rd.get("id") in reading_ids})
            rules = []
            for item in (use["rules"] if use is not None else ()):
                rules.append({"id": item["id"], "version": copy.deepcopy(item["version"]),
                              "declaration_digest": digest(item["declaration"]),
                              "digest_scope": "captured native parser.data.rules object"})
            sources = [{"source_id": oc["assumption"]["premise_id"] if oc is not None else cand["id"],
                        "observation_id": None, "reading_revision": None, "text": target_text, "span": None,
                        "unknown_span": source_echo["unknown_span"]}]
            ledger = snapshot.get("reading_ledger") if isinstance(snapshot, dict) else None
            records = ledger.get("records") if isinstance(ledger, dict) else None
            for prem in (use["premises"] if use is not None else ()):
                if prem["premise_id"] == oc["assumption"]["premise_id"]:
                    continue
                ref = prem.get("source_ref") if isinstance(prem.get("source_ref"), dict) else {}
                oid, rev = ref.get("observation_id"), ref.get("reading_revision")
                stext = None
                if isinstance(records, dict) and isinstance(oid, str) and type(rev) is int and rev >= 1:
                    entry = records.get(oid)
                    versions = entry.get("versions") if isinstance(entry, dict) else None
                    record = versions[rev - 1] if isinstance(versions, list) and rev <= len(versions) else None
                    if isinstance(record, dict) and record.get("observation_id") == oid \
                            and record.get("reading_revision") == rev and isinstance(record.get("source"), str):
                        stext = record["source"]
                fact = prem.get("original_fact") if isinstance(prem.get("original_fact"), dict) else {}
                ev_ = fact.get("evidence") if isinstance(fact.get("evidence"), dict) else {}
                start, end, etext = ev_.get("start"), ev_.get("end"), ev_.get("text")
                span = [start, end] if (stext is not None and type(start) is int and type(end) is int
                                         and 0 <= start <= end <= len(stext) and isinstance(etext, str)
                                         and stext[start:end] == etext) else None
                sources.append({"source_id": prem["premise_id"],
                                "observation_id": oid if isinstance(oid, str) else None,
                                "reading_revision": rev if type(rev) is int else None, "text": stext,
                                "span": span})
            sources.append({"source_id": input_id, "kind": "question", "input_id": input_id, "text": text,
                            "observation_id": None, "reading_revision": None, "span": None})
            composition, seen = [], {}
            fref = cand.get("source_ref") if isinstance(cand.get("source_ref"), dict) else {}
            composition.append({"reference": "frame", "annotation_sha256": fref.get("annotation_sha256"),
                                "declaration_digest": fref.get("annotation_sha256"),
                                "source_ref": copy.deepcopy(cand.get("source_ref"))})
            composition.append({"reference": "policy", "declaration_digest": digest(cand.get("policy_source")),
                                "digest_scope": "selected candidate policy_source capsule",
                                "policy_source": copy.deepcopy(cand.get("policy_source"))})
            for e in chosen["entries"]:
                rd = e["reading"]
                qref = rd.get("query_ref") if isinstance(rd.get("query_ref"), dict) else {}
                arow = copy.deepcopy(e["association"])
                for name, value, declared_digest in (("query", qref, qref.get("annotation_sha256")),
                                                     ("association", arow, digest(arow))):
                    marker = (name, _canonical(value))
                    if marker in seen:
                        seen[marker]["reading_ids"].append(rd.get("id"))
                        continue
                    item = {"reference": name, "reading_ids": [rd.get("id")],
                            "declaration_digest": declared_digest, "source_ref": copy.deepcopy(value)}
                    if name == "query":
                        item["annotation_sha256"] = qref.get("annotation_sha256")
                        item["index"] = qref.get("index")
                        item["graph_source"] = copy.deepcopy(qref.get("graph_source"))
                    else:
                        item["digest_scope"] = ("whole selected projection relation_hypothesis_queries row "
                                                "(policy_index,frame_index,query_index,query_ref,predicate,"
                                                "known_slot,roles,terminal,association_source)")
                    seen[marker] = item
                    composition.append(item)
            for k in (keys if status == "conditional" else keys[1:]):
                composition.append({"reference": k, "declaration_digest": digest({"template": preplies[k],
                                                                                "graph_source": rsources[k]}),
                                    "digest_scope": "{template,graph_source} reply declaration",
                                    "template": preplies[k], "graph_source": copy.deepcopy(rsources[k])})
            attempt.update({"status": status, "source": source_echo,
                            "query": copy.deepcopy(rd0["virtual_record"]),
                            "selected": {"candidate_id": cand["id"], "reading_ids": reading_ids,
                                         "group_id": first_entry["group_id"],
                                         "outcome_index": first_entry["outcome_index"],
                                         "match": copy.deepcopy(match), "support_ids": selected_ids}})
            final["meaning"] = {"act": "hold", "reason": "relation_meaning_pending", "said": target_text}
            final["answer"] = answer
            final["relation_attempt"] = attempt
            usage = {"assumptions": assumptions, "rules": rules, "sources": sources, "composition": composition}
            if not _valid_json(final, byte_limit=1048576) or not _valid_json(usage, byte_limit=262144):
                stop("result_invalid", "validation")
            self._active["_relation_usage"] = usage
            return final
        except Exception as exc:
            args = exc.args if isinstance(exc, ValueError) and len(exc.args) == 2 else ("driver_failed", "driver")
            code, stage = (str(a)[:128] for a in args)
            failed = copy.deepcopy(out)
            failed["relation_attempt"] = {"schema": schema, "status": "gap",
                                          "gaps": [{"code": code, "stage": stage, "reading_id": None,
                                                    "candidate_id": None, "group_id": None}]}
            return failed

    def _relation_proof_use(self, acquisition, outcome, match):
        world = outcome["conditional"]
        table = {}
        for entry in world.get("proof_bundles") or ():
            for row in entry.get("bundles") or ():
                if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                    raise ValueError("proof_missing_link", "proof")
                if row["id"] in table:
                    raise ValueError("proof_duplicate_id", "proof")
                table[row["id"]] = row
        sources = {}
        for desc in world.get("fact_sources") or ():
            if not isinstance(desc, dict) or not isinstance(desc.get("premise_id"), str):
                raise ValueError("proof_missing_link", "proof")
            if desc["premise_id"] in sources:
                raise ValueError("proof_duplicate_source", "proof")
            sources[desc["premise_id"]] = desc
        rules = acquisition["parser"].data.get("rules") or []
        if not isinstance(rules, list):
            raise ValueError("proof_rule_unmatched", "proof")
        own = outcome["assumption"]["premise_id"]
        visits = [0]
        paths, used_rules, premises, bundles_seen = [], {}, {}, []
        found_own = [False]

        def visit(bid, ancestry, trail, depth):
            visits[0] += 1
            if visits[0] > 512 or depth > 32:
                raise ValueError("proof_cap", "proof")
            if bid in ancestry:
                raise ValueError("proof_cycle", "proof")
            row = table.get(bid)
            if row is None:
                raise ValueError("proof_missing_link", "proof")
            if bid not in bundles_seen:
                bundles_seen.append(bid)
            trail = trail + [bid]
            ancestry = ancestry | {bid}
            links = row.get("premise_fact_ids")
            if not isinstance(links, list):
                raise ValueError("proof_missing_link", "proof")
            if row.get("kind") not in ("asserted", "derived"):
                raise ValueError("proof_kind_unsupported", "proof")
            if row.get("kind") == "asserted":
                for pid in links:
                    visits[0] += 1
                    if visits[0] > 512:
                        raise ValueError("proof_cap", "proof")
                    desc = sources.get(pid)
                    if desc is None:
                        raise ValueError("proof_missing_link", "proof")
                    premises.setdefault(pid, desc)
                    if pid == own:
                        found_own[0] = True
                    paths.append({"bundles": trail, "leaf": pid})
                return
            rid = row.get("rule")
            if not isinstance(rid, str):
                raise ValueError("proof_rule_unmatched", "proof")
            matched = [r for r in rules if isinstance(r, dict) and r.get("id") == rid]
            if len(matched) != 1 or not _native_identity_equal(
                    row.get("rule_version"), matched[0].get("version", matched[0].get("rule_version"))):
                raise ValueError("proof_rule_unmatched", "proof")
            used_rules.setdefault(rid, (row.get("rule_version"), matched[0]))
            for pid in links:
                visit(pid, ancestry, trail, depth + 1)

        for sid in match.get("support_ids") or ():
            visit(sid, frozenset(), [], 0)
        return {"own_hypothesis": found_own[0], "paths": paths, "bundles": bundles_seen,
                "used_bundle_rows": [copy.deepcopy(table[bid]) for bid in bundles_seen],
                "premises": [copy.deepcopy(p) for p in premises.values()],
                "rules": [{"id": k, "version": copy.deepcopy(v[0]), "declaration": copy.deepcopy(v[1])}
                          for k, v in used_rules.items()],
                "visits": visits[0]}

    def _result(self, result):
        out = copy.deepcopy(result) if isinstance(result, dict) else {"result": copy.deepcopy(result)}
        if isinstance(out.get("meaning"), dict) and out["meaning"].get("act") == "hold":
            out.setdefault("status", "unresolved")
            out.setdefault("transitions", [])
        out["memory_revision"] = self._revision()
        out["conversation_id"] = self.conversation_id
        return out

    def _fresh_parser(self):
        parser = self.memory.parser()
        parser.effort = self.effort
        return parser

    def _rehydrate(self, snapshot, head_limit=None):
        """Fresh ordinary parser over active memory; archived readings come back from the context ledger.

        ``head_limit`` bounds the installed heads a loaded ledger may claim (the SAVED session head)."""
        parser = self._fresh_parser()
        self.context._parser_instance = parser
        self._parser_revision = self._revision()
        # the parser refresh drops every cache derived from the previous parser
        self.context._verb_cache = None
        self.context._replay_cache = None
        self.context._grammar_cache = (parser, hashlib.sha256(
            dumps({"data": parser.data, "language_pack": parser.language_pack}).encode("utf-8")).hexdigest())
        self.context.parser_base_sha256 = self.base_sha256
        self.context.installed_memory_head = self._parser_revision if head_limit is None else head_limit
        self.context.restore(copy.deepcopy(snapshot))
        self.context.installed_memory_head = self._parser_revision
        # a successfully restored snapshot is the new rollback checkpoint
        self._checkpoint = copy.deepcopy(snapshot)

    def _binding(self):
        seq, change_id = self.memory._store.head()
        return {"seq": seq, "change_id": change_id}

    def _model_binding(self):
        binding = {"content_fingerprint": self.model.content_fingerprint,
                   "effective_key": self.model.effective_key, "parser_sha256": self.base_sha256}
        if self._selected is not None:
            binding.update(graph_member_path=self._selected.member_path,
                           graph_member_sha256=self._selected.member_sha256,
                           knowledge_binding=self._knowledge_binding)
        return binding

    def _check_model_binding(self, state):
        """Reject graph/model reuse before any archived history is restored."""
        if state.get("model_binding") != self._model_binding():
            raise ValueError("session state belongs to a different selected model")

    def _check_binding(self, state):
        """The saved store position must be an ancestor of this store, by actual change identity."""
        binding = state.get("memory_binding")
        if not (isinstance(binding, dict) and set(binding) == {"seq", "change_id"}):
            raise ValueError("session state has no memory binding")
        seq, change_id = binding["seq"], binding["change_id"]
        if not _nonneg(seq) or seq != state["memory_revision"]:
            raise ValueError("memory binding differs from memory revision")
        if seq == 0:
            if change_id is not None:
                raise ValueError("malformed memory binding")
            return
        if not isinstance(change_id, str) or not change_id or seq > self.memory._store.head()[0]:
            raise ValueError("malformed memory binding")
        try:
            actual = self.memory._store.change(seq)["change_id"]
        except Exception as error:
            raise ValueError("session state belongs to a different memory history") from error
        if actual != change_id:
            raise ValueError("session state belongs to a different memory history")

    def _migrate_v1(self, state, context):
        """Expand v1 source pins into one archived record per observation slot (validated exactly as v1 was)."""
        pins, observations = state["pinned_readings"], context["observations"]
        readings = context.get("readings") or {}
        if not isinstance(readings, dict) or set(pins) != {s.strip() for s in observations}:
            raise ValueError("pins must cover exactly the accepted observations")
        for key, pin in pins.items():
            if not (isinstance(pin, dict) and _nonneg(pin.get("memory_revision"))
                    and pin["memory_revision"] <= state["memory_revision"]):
                raise ValueError("malformed pinned reading")
            if pin.get("unread") is True and pin.get("reading") is None:
                if key in readings:
                    raise ValueError("unread history cannot carry an invented reading")
            elif not isinstance(pin.get("reading"), dict) or readings.get(key) != pin["reading"]:
                raise ValueError("pinned reading differs from context interpretation")
        if set(readings) != {key for key, pin in pins.items() if pin["reading"] is not None}:
            raise ValueError("context readings must match archived interpretations")
        counts = {}
        for source in observations:
            counts[source.strip()] = counts.get(source.strip(), 0) + 1
        ids, records = [], {}
        for number, source in enumerate(observations, 1):
            pin, oid = pins[source.strip()], "o%d" % number
            ids.append(oid)
            gone = pin["reading"] is None
            records[oid] = {"active": 1, "versions": [make_record(
                oid, 1, source, copy.deepcopy(pin["reading"]), base=state["base_sha256"],
                head=pin["memory_revision"], unavailable=gone,
                reason="unavailable" if gone else ("legacy_source_shared" if counts[source.strip()] > 1
                                                   else "initial"))]}
        upgraded = {key: value for key, value in context.items() if key != "readings"}
        upgraded.update(schema=CONTEXT_SCHEMA, observation_ids=ids,
                        reading_ledger={"next": len(ids) + 1, "records": records})
        return upgraded

    def _load(self, requested_id):
        with open(self.state_path, encoding="utf-8") as handle:
            state = json.load(handle)
        if isinstance(state, dict) and state.get("schema") == SCHEMA_V1:
            return self._load_v1(state, requested_id)
        if not isinstance(state, dict) or state.get("schema") != SCHEMA:
            raise ValueError("unsupported session state schema")
        if state.get("base_sha256") != self.base_sha256:
            raise ValueError("session state belongs to a different base")
        if state.get("language") != self.language:
            raise ValueError("session state language mismatch")
        self._check_model_binding(state)
        saved_id = _text("conversation_id", state.get("conversation_id"))
        if requested_id is not None and requested_id != saved_id:
            raise ValueError("conversation_id differs from saved state")
        context = state.get("context")
        if not isinstance(context, dict) or context.get("schema") != CONTEXT_SCHEMA:
            raise ValueError("unsupported context snapshot")
        if not _nonneg(state.get("turn_counter")) or not _nonneg(state.get("memory_revision")) \
                or state["memory_revision"] > self._revision():
            raise ValueError("malformed session state")
        self._check_binding(state)
        observations = context.get("observations")
        if not isinstance(observations, list) or any(not isinstance(source, str) for source in observations):
            raise ValueError("malformed context observations")
        self._restore_state(saved_id, state["turn_counter"], context, state["memory_revision"])
        if self._selected is not None:
            known_gap = {"code": "native_history_unavailable"}
            try:
                # the retained prior carrier is restored whenever it validates; a reported known
                # finite gap is preserved exactly and never by itself erases that history
                self._native_turns = self._native_history_valid(
                    state.get("selected_graph_turns", []), state["turn_counter"])
                if "selected_graph_gap" not in state:
                    self._native_history_gap = None
                elif state["selected_graph_gap"] == known_gap:
                    self._native_history_gap = dict(known_gap)
                else:
                    raise ValueError("native history gap metadata invalid")
            except Exception:
                self._native_turns, self._native_history_gap = [], dict(known_gap)
        if self._learning_enabled and "learning_collection" in state:
            env = state["learning_collection"]
            args = (env, state, self._model_binding(), self._revision(),
                    getattr(self.memory, "payload_bytes_limit", None),
                    getattr(self.memory, "validation_limit", None))
            try:
                try:
                    restored = self._collection_check(*args, None)
                except ValueError as exc:
                    if str(exc) != "witness_required":
                        raise
                    try:
                        views = self.memory.candidates()
                    except Exception:
                        raise ValueError("collection_metadata_unavailable")
                    restored = self._collection_check(*args, views)
                self._learning = {"targets": restored[0], "draft": restored[1]}
                self._learning_gap = env.get("gap")
            except Exception as exc:
                self._learning = {"targets": {}, "draft": None}
                self._learning_gap = {"code": str(exc) if str(exc).startswith("collection_")
                                      and len(str(exc)) <= 128 else "collection_unavailable"}
        elif self._learning_enabled:
            self._learning_gap = {"code": "collection_unavailable"}
        if self._learning_enabled and "query_learning_source" in state:
            try:
                checked = self._query_source_check(state["query_learning_source"],
                                                   bound_turn=state["turn_counter"],
                                                   bound_head=state["memory_binding"])
                self._learning["query_source"], self._learning["query_source_gap"] = \
                    checked["source"], checked["gap"]
            except Exception as exc:
                self._learning["query_source"] = None
                self._learning["query_source_gap"] = {
                    "code": str(exc) if isinstance(exc, ValueError) and str(exc) in (
                        "query_source_unavailable", "query_source_invalid", "query_source_owner_unavailable",
                        "query_source_binding_mismatch", "query_source_input_mismatch",
                        "query_source_overflow") else "query_source_invalid"}
        if self._learning_enabled and "query_learning_draft" in state:
            try:
                checked = self._query_learning_check(state["query_learning_draft"],
                                                     bound_turn=state["turn_counter"],
                                                     bound_head=state["memory_binding"])
                pair = None
                if checked.get("pending") is not None:
                    pair = {"pending": checked["pending"], "draft": checked["draft"]}
                self._learning["query_draft"], self._learning["query_draft_gap"] = pair, checked["gap"]
            except Exception as exc:
                self._learning["query_draft"] = None
                self._learning["query_draft_gap"] = {
                    "code": str(exc) if isinstance(exc, ValueError) and str(exc).startswith("query_learning_")
                    and len(str(exc)) <= 64 else "query_learning_invalid"}

    def _restore_state(self, saved_id, turn_counter, context, saved_head):
        # context.restore validates IDs, coverage, source binding, revisions, base and the saved head
        self._rehydrate(context, saved_head)
        self.conversation_id, self.turn_counter = saved_id, turn_counter

    def _load_v1(self, state, requested_id):
        if state.get("base_sha256") != self.base_sha256:
            raise ValueError("session state belongs to a different base")
        if state.get("language") != self.language:
            raise ValueError("session state language mismatch")
        saved_id = _text("conversation_id", state.get("conversation_id"))
        if requested_id is not None and requested_id != saved_id:
            raise ValueError("conversation_id differs from saved state")
        context = state.get("context")
        if not isinstance(context, dict) or context.get("schema") != "reasoning-context-v10" \
                or not isinstance(state.get("pinned_readings"), dict) or not _nonneg(state.get("turn_counter")) \
                or not _nonneg(state.get("memory_revision")) \
                or not isinstance(context.get("observations"), list) \
                or any(not isinstance(s, str) for s in context["observations"]):
            raise ValueError("malformed session state")
        if state["memory_revision"] > self._revision():
            raise ValueError("malformed session state")
        # Envelope migration only: an unstamped v1 cannot certify the original graph/store, so it is
        # refused (and left untouched) rather than restamped.  Both genuine bindings must match first.
        self._check_model_binding(state)
        self._check_binding(state)
        self._restore_state(saved_id, state["turn_counter"], self._migrate_v1(state, context),
                            state["memory_revision"])
        self.save()     # atomic upgrade to the v2 format
