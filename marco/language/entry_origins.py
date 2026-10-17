"""Pure carrier helpers for installed-expression entry origins."""

from __future__ import annotations

import copy
import json
import re

_SCOPE = "installed_expression_origin"
_ORIGIN_FIELDS = frozenset(
    {
        "scope",
        "candidate_id",
        "rule_id",
        "rule_revision",
        "accepted_change_id",
        "teaching",
        "graph_binding",
    }
)
_TEACHING_FIELDS = frozenset({"conversation_id", "turn_id"})
_GRAPH_BINDING = re.compile(r"[0-9a-f]{64}")
_MAX_BYTES = 8192


class EntryOriginError(RuntimeError):
    """Entry-origin provenance metadata fault, distinct from semantic errors."""


def _nonblank(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value


def _strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validated_entry_origin(origin: dict | None) -> dict | None:
    """Return a detached validated copy of an origin; None stays unknown."""
    if origin is None:
        return None
    if not isinstance(origin, dict):
        raise ValueError("entry origin must be a dict or None")
    if set(origin.keys()) != _ORIGIN_FIELDS or not all(
        isinstance(k, str) for k in origin
    ):
        raise ValueError("entry origin fields must be exactly the supported set")
    if origin["scope"] != _SCOPE or not isinstance(origin["scope"], str):
        raise ValueError("entry origin scope is invalid")
    _nonblank(origin["candidate_id"], "candidate_id")
    _nonblank(origin["rule_id"], "rule_id")
    _nonblank(origin["accepted_change_id"], "accepted_change_id")
    revision = origin["rule_revision"]
    if not _strict_int(revision) or revision <= 0:
        raise ValueError("rule_revision must be a positive int")
    teaching = origin["teaching"]
    if not isinstance(teaching, dict) or set(teaching.keys()) != _TEACHING_FIELDS:
        raise ValueError("teaching fields must be exactly conversation_id, turn_id")
    _nonblank(teaching["conversation_id"], "conversation_id")
    _nonblank(teaching["turn_id"], "turn_id")
    binding = origin["graph_binding"]
    if binding is not None and (
        not isinstance(binding, str) or _GRAPH_BINDING.fullmatch(binding) is None
    ):
        raise ValueError("graph_binding must be None or 64 lowercase hex chars")
    try:
        encoded = json.dumps(
            origin,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("entry origin is not canonical finite JSON") from exc
    if len(encoded) > _MAX_BYTES:
        raise ValueError("entry origin exceeds 8192 bytes")
    return copy.deepcopy(origin)


def remap_entry_origins(
    origins: list[dict | None] | None,
    *,
    input_count: int,
    kept_indices: list[int],
    derived_from: list[int] = (),
) -> list[dict | None]:
    """Select kept rows then append derived copies, preserving unknowns."""
    if not _strict_int(input_count) or input_count < 0:
        raise ValueError("input_count must be a nonnegative int")
    if origins is not None:
        if not isinstance(origins, list) or len(origins) != input_count:
            raise ValueError("origins must be None or a list of input_count rows")
        validated = [validated_entry_origin(row) for row in origins]
    else:
        validated = None
    if not isinstance(kept_indices, list):
        raise ValueError("kept_indices must be a list")
    if not isinstance(derived_from, (list, tuple)):
        raise ValueError("derived_from must be a list or tuple")
    for idx in kept_indices:
        if not _strict_int(idx) or not 0 <= idx < input_count:
            raise ValueError("kept_indices must be valid input indices")
    if len(set(kept_indices)) != len(kept_indices):
        raise ValueError("kept_indices must be unique")
    kept = set(kept_indices)
    for idx in derived_from:
        if not _strict_int(idx) or not 0 <= idx < input_count or idx not in kept:
            raise ValueError("derived_from must reference retained input indices")
    order = [*kept_indices, *derived_from]
    if validated is None:
        return [None for _ in order]
    return [copy.deepcopy(validated[i]) for i in order]
