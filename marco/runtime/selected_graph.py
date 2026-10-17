"""Prepare one explicitly selected ``.kg`` member under its own pack's encoder.

The graph text is parsed with the existing pure parser and prepared by the
native engine with the disk cache off, inside the selected model's encoder
context. The metadata records configuration and source authorship only.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
import math

from encoder import EncoderRuntime
from marco.storage.graph_text import parse
from pack_model import PackModel


class SelectedGraphError(ValueError):
    def __init__(self, stage, code, error_type="SelectedGraphError"):
        self.stage = stage
        self.code = code
        self.error_type = error_type
        super().__init__("%s:%s:%s" % (stage, code, error_type))


@dataclass(frozen=True)
class PreparedSelectedGraph:
    member_path: str
    member_bytes: bytes
    member_sha256: str
    model_content_fingerprint: str
    model_declaration: dict
    reference_encoder_declaration: dict
    parsed_graph_snapshot: dict
    prepared_graph: dict


_ENCODER_KEYS = ("mode", "dimensions", "jamo_weight", "smoothing", "route_threshold",
                 "cluster_threshold", "goal_similarity_threshold", "device")
_ATTRS = {"mode": "mode", "dimensions": "dimensions", "jamo_weight": "jamo_weight",
          "smoothing": "smoothing", "route_threshold": "route_thresh",
          "cluster_threshold": "cluster_thresh",
          "goal_similarity_threshold": "goal_sim_thresh", "device": "device"}
_UNIT = ("jamo_weight", "smoothing", "route_threshold", "cluster_threshold",
         "goal_similarity_threshold")


def _unit(v):
    # Type and bounded range first; a huge int must never reach math.isfinite.
    return type(v) in (int, float) and 0 <= v <= 1 and math.isfinite(v)


def _check_encoder(spec):
    if type(spec) is not dict or set(spec) != set(_ENCODER_KEYS):
        return False
    d = spec["dimensions"]
    return (type(spec["mode"]) is str
            and type(spec["device"]) is str
            and type(d) is int and 256 <= d <= 65536
            and all(_unit(spec[k]) for k in _UNIT))


def _supported_encoder(spec):
    return spec["mode"] == "문자" and spec["device"] == "cpu"


def _raw_encoder_declaration(language_bytes):
    """Read the encoder declaration from the raw language member bytes only."""
    try:
        pack = json.loads(language_bytes)
    except Exception:
        return None
    if type(pack) is not dict:
        return None
    return pack.get("인코더", pack.get("encoder", {}))


def _fingerprint_matches(expected, content):
    if type(content) is not str or not content.isascii():
        return False
    try:
        return hmac.compare_digest(expected, content)
    except Exception:
        return False


def prepare_selected_graph(model, assets, graph_member_path):
    import engine
    if type(model) is not PackModel:
        raise SelectedGraphError("binding", "selected_model_invalid")
    if (type(assets) is not dict
            or not all(type(k) is str and type(v) is bytes for k, v in assets.items())):
        raise SelectedGraphError("binding", "asset_table_invalid")
    if type(graph_member_path) is not str or not graph_member_path.endswith(".kg"):
        raise SelectedGraphError("binding", "graph_member_missing_or_nonbytes")
    if graph_member_path not in assets:
        raise SelectedGraphError("binding", "graph_member_missing_or_nonbytes")
    assets = dict(assets)
    try:
        declaration = model.declaration
        language = declaration.get("language") if type(declaration) is dict else None
        content = model.content_fingerprint
        encoder = model.encoder
    except Exception:
        raise SelectedGraphError("binding", "selected_model_invalid") from None
    if type(declaration) is not dict:
        raise SelectedGraphError("binding", "selected_model_invalid")
    if type(language) is not str or language not in assets:
        raise SelectedGraphError("binding", "selected_model_invalid")
    try:
        expected = hashlib.sha256(json.dumps(
            {"assets": [{"path": p, "sha256": hashlib.sha256(assets[p]).hexdigest()}
                        for p in sorted(assets)],
             "model": declaration}, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True).encode()).hexdigest()
    except Exception:
        raise SelectedGraphError("binding", "full_binding_mismatch") from None
    if not _fingerprint_matches(expected, content):
        raise SelectedGraphError("binding", "full_binding_mismatch")
    if type(encoder) is not EncoderRuntime:
        raise SelectedGraphError("encoder", "unsupported_selected_encoder")
    # The raw language member in the bound table is the declaration authority,
    # not the cached ``model.language`` property.
    spec = _raw_encoder_declaration(assets[language])
    if not _check_encoder(spec):
        raise SelectedGraphError("encoder", "encoder_declaration_incomplete_or_mismatched")
    if not _supported_encoder(spec):
        raise SelectedGraphError("encoder", "unsupported_selected_encoder")
    for key, attr in _ATTRS.items():
        try:
            actual = getattr(encoder, attr, None)
        except Exception:
            raise SelectedGraphError(
                "encoder", "encoder_declaration_incomplete_or_mismatched") from None
        if type(actual) is not type(spec[key]) or actual != spec[key]:
            raise SelectedGraphError("encoder", "encoder_declaration_incomplete_or_mismatched")
    data = assets[graph_member_path]
    try:
        parsed = parse(data)
    except Exception as exc:
        raise SelectedGraphError("parse", "graph_text_invalid", type(exc).__name__) from None
    if type(parsed) is not dict:
        raise SelectedGraphError("parse", "graph_text_invalid")
    if parsed.get("포함"):
        raise SelectedGraphError("include", "includes_unsupported")
    try:
        snapshot = deepcopy(parsed)
        work = deepcopy(parsed)
        with encoder.activate():
            prepared = engine._prepare_graph(work, cache_disk=False)
    except Exception as exc:
        raise SelectedGraphError("prepare", "native_prepare_invalid", type(exc).__name__) from None
    if type(prepared) is not dict:
        raise SelectedGraphError("prepare", "native_prepare_invalid")
    return PreparedSelectedGraph(
        member_path=graph_member_path,
        member_bytes=data,
        member_sha256=hashlib.sha256(data).hexdigest(),
        model_content_fingerprint=content,
        model_declaration=declaration,
        reference_encoder_declaration=dict(spec),
        parsed_graph_snapshot=snapshot,
        prepared_graph=prepared,
    )


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _overlay_effective(prepared, assets, graph_pack_path, graph_overlay):
    """Detached effective raw graph and origin capsule of the committed node/edge overlay."""
    from marco.storage import kgpack
    from marco.storage.graph_view import (GraphView, OverlayAttachment, PackBase,
                                          pack_content_sha256)
    try:
        if type(graph_pack_path) is not str or not graph_pack_path:
            raise SelectedGraphError("overlay", "graph_pack_path_invalid")
        if type(graph_overlay) is not OverlayAttachment:
            raise SelectedGraphError("overlay", "graph_overlay_invalid")
        try:
            manifest, members = kgpack.read(graph_pack_path, verify=True)
        except Exception as exc:
            raise SelectedGraphError("overlay", "base_pack_unreadable", type(exc).__name__) from None
        if (type(members) is not dict or members != assets
                or any(members[k] != assets[k] for k in assets)):
            raise SelectedGraphError("overlay", "base_assets_mismatch")
        if (type(manifest) is not dict
                or _canonical(manifest.get("model")) != _canonical(prepared.model_declaration)):
            raise SelectedGraphError("overlay", "base_declaration_mismatch")
        base_sha = pack_content_sha256(manifest)
        if (type(graph_overlay.base_sha256) is not str
                or not hmac.compare_digest(base_sha.encode(), graph_overlay.base_sha256.encode())):
            raise SelectedGraphError("overlay", "base_sha_mismatch")
        with graph_overlay._open() as store:
            meta = store.meta()
            if meta["base_sha256"] != base_sha:
                raise SelectedGraphError("overlay", "base_sha_mismatch")
            build_id = meta["base_build_id"]
            view = GraphView(PackBase(manifest, dict(members)), store, base_build_id=build_id)
            view.check()
            seq, change_id = view.key
            rules = view.rule_changes()
            effective, origins = view.graph_with_origins(prepared.member_path)
        if rules:
            raise SelectedGraphError("overlay", "rule_changes_unsupported")
        if type(effective) is not dict:
            raise SelectedGraphError("overlay", "effective_graph_invalid")
        if effective.get("포함"):
            raise SelectedGraphError("include", "includes_unsupported")
        if "_미지로그" in effective:
            raise SelectedGraphError("prepare", "unknown_log_key_refused")
        capsule = {
            "base_manifest_sha256": base_sha,
            "base_build_id": build_id,
            "head_seq": seq,
            "change_id": change_id,
            "effective_graph_digest": hashlib.sha256(_canonical(effective)).hexdigest(),
            "rule_changes_applied": False,
            "origin_catalog": {"status": "installed_not_used", "nodes": origins["nodes"],
                               "edges": origins["edges"]},
        }
        capsule = json.loads(json.dumps(capsule, allow_nan=False))
    except SelectedGraphError:
        raise
    except Exception as exc:
        raise SelectedGraphError("overlay", "overlay_unavailable", type(exc).__name__) from None
    return effective, capsule


def judge_selected_graph(model, assets, graph_member_path, text, *, trace_ledger=None, conversation_id=None,
                         streak_A=0, graph_pack_path=None, graph_overlay=None):
    """Native engine.judge on a freshly prepared selected graph; optionally recorded through DialogueTrace."""
    import engine
    from marco.trace.ledger import Ledger
    from marco.runtime.dialogue_trace import DialogueTrace
    from marco.trace import runtime as rt

    if type(text) is not str:
        raise TypeError("text must be str")
    if type(streak_A) is not int or streak_A < 0:
        raise ValueError("streak_A must be an int >= 0")
    if trace_ledger is None:
        if conversation_id is not None:
            raise ValueError("conversation_id requires trace_ledger")
    else:
        if type(trace_ledger) is not Ledger:
            raise TypeError("trace_ledger must be a Ledger")
        if getattr(trace_ledger, "fsync", None) is not True:
            raise ValueError("trace_ledger must fsync")
        ledger_runtime = getattr(trace_ledger, "runtime", None)
        if type(ledger_runtime) is not dict or ledger_runtime:
            raise ValueError("trace_ledger runtime must be an empty dict")
        if type(conversation_id) is not str or not conversation_id:
            raise ValueError("conversation_id must be a nonempty str")
    if type(model) is not PackModel:
        raise SelectedGraphError("binding", "selected_model_invalid")
    if (graph_pack_path is None) != (graph_overlay is None):
        raise SelectedGraphError("overlay", "pack_and_overlay_required_together")

    encoder = model.encoder
    if type(assets) is dict:
        assets = dict(assets)
    prepared = prepare_selected_graph(model, assets, graph_member_path)
    if model.encoder is not encoder or type(encoder) is not EncoderRuntime:
        raise SelectedGraphError("encoder", "encoder_changed_during_prepare")
    graph = deepcopy(prepared.prepared_graph)
    if "_미지로그" in graph:
        raise SelectedGraphError("prepare", "unknown_log_key_refused")
    capsule = None
    if graph_pack_path is not None or graph_overlay is not None:
        effective, capsule = _overlay_effective(prepared, assets, graph_pack_path, graph_overlay)
        try:
            with encoder.activate():
                graph = engine._prepare_graph(deepcopy(effective), cache_disk=False)
        except Exception as exc:
            raise SelectedGraphError("overlay", "native_prepare_invalid", type(exc).__name__) from None
        if type(graph) is not dict or "_미지로그" in graph:
            raise SelectedGraphError("overlay", "native_prepare_invalid")

    fingerprint = prepared.model_content_fingerprint
    member_path = prepared.member_path
    member_sha = prepared.member_sha256
    reference = deepcopy(prepared.reference_encoder_declaration)
    declaration = deepcopy(prepared.model_declaration)
    language_member_path = declaration["language"]
    language_raw = assets[language_member_path] if type(assets) is dict else None
    if type(language_raw) is not bytes:
        raise SelectedGraphError("language", "language_member_missing")
    language_member_sha = hashlib.sha256(language_raw).hexdigest()
    try:
        from language_components import decode_language_pack
        language_pack = decode_language_pack(json.loads(language_raw.decode("utf-8")), language_member_path)
    except SelectedGraphError:
        raise
    except Exception:
        raise SelectedGraphError("language", "language_pack_decode_refused")
    cfg_digest = hashlib.sha256(json.dumps(reference, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    stamp = {
        "model": {"content_fingerprint": fingerprint, "effective_key": None},
        "pack": declaration["language"],
        "encoder": {"reference": "encoder.EncoderRuntime", "declaration_digest": cfg_digest},
        "realizer": {"reference": None, "declaration_digest": None},
        "extras": {"graph_member_path": member_path, "graph_member_sha256": member_sha,
                   "language_member_path": language_member_path,
                   "language_member_sha256": language_member_sha,
                   "config": deepcopy(reference)},
    }

    if capsule is not None:
        stamp["extras"]["graph_overlay"] = deepcopy(capsule)

    def identity(candidates):
        out = {"model_content_fingerprint": fingerprint, "graph_member_path": member_path,
               "graph_member_sha256": member_sha, "reference_encoder_declaration": deepcopy(reference),
               "candidates": candidates, "proof_status": "partial", "used_edge_path": None,
               "used_learning": None, "used_readings": None, "used_rule": None}
        if capsule is not None:
            out["graph_overlay"] = deepcopy(capsule)
        return out

    def bound(value):
        return value if type(value) is str else None

    def compute():
        share, groups = {}, []
        sink = (lambda group: groups.append(list(group))) if trace_ledger is not None else None
        with encoder.activate():
            tag, line = engine.judge(graph, text, streak_A, share, language_pack=language_pack, trace_sink=sink)
        conf = share.get("확신")
        if type(conf) in (int, float) and math.isfinite(conf):
            conf = float(conf)
        else:
            conf = None
        candidates = {"evidence": bound(share.get("증거")), "claim": bound(share.get("주장")),
                      "native_confidence": conf}
        reply = line if type(line) is str else None
        gap = None if tag == "인정" else tag
        status = "answered" if tag == "인정" else "held"
        if tag == "목표주장":
            lines = graph.get("대사")
            authored = lines.get("목표주장") if type(lines) is dict else None
            if type(authored) is not str or not authored.strip():
                reply, status, gap = None, "held", "authored_reply_missing"
        result = {"verdict": tag, "reply": reply, "status": status, "gap": gap,
                  "provenance": identity(candidates), "trace": None}
        return result, (groups[0] if groups else [])

    if trace_ledger is None:
        return compute()[0]

    dialogue = DialogueTrace(trace_ledger, conversation=conversation_id, runtime_stamp=stamp,
                             provenance={"selected_native_judgement": identity(None)})
    attempt = dialogue.begin(text)
    try:
        result, rows = compute()
    except Exception as exc:
        try:
            dialogue._record_failure(attempt, None, exc, "judge",
                                     {"selected_native_judgement": identity(None)})
        except Exception:
            pass
        raise
    tag, reply = result["verdict"], result["reply"]
    envelope = {"phase": "answer", "answer": {"answer": reply or "", "known": tag == "인정",
                "trace": {"verdict": tag, "mode": "selected_graph",
                          "reasoning": {"operator": "engine.judge", "transitions": []}}}}
    final = {"selected_native_judgement": deepcopy(result["provenance"])}

    def pending(ledger, input_id, trace_id):
        base = rt.contract_provenance(stamp, final)["base"]
        runtime = {"build": base["build"], "pack": base["pack"]}
        ids, root = [], None
        for kind, fields in rows:
            fields = dict(fields)
            payload = dict(fields.get("payload") or {})
            if kind == "evidence_found":
                kind = "routing_selected"
                payload["candidate_only"] = True
                payload["selected"] = payload.get("ref")
                fields["epistemic_status"] = "unknown"
            payload["attempt_id"] = attempt.attempt_id
            fields["payload"] = rt.plain_json(payload, "payload")
            fields["runtime"] = runtime
            event = ledger.append(kind, trace_id, parent_ids=[root or input_id], **fields)
            root = root or event["event_id"]
            ids.append(event["event_id"])
        return ids

    try:
        summary = dialogue.finish(attempt, envelope, provenance=final, pending_flush=pending)
    except Exception as exc:
        try:
            exc.executed_result = dict(result, trace=None)
        except Exception:
            pass
        raise
    result["trace"] = summary
    return result
