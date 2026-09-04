# -*- coding: utf-8 -*-
"""의미 후보를 검증 가능한 상태 JSON으로 바꾸는 어댑터.

이 모듈은 답을 만들지 않는다. 모델 출력은 항상 ``candidate``이며,
``validate``가 원문의 위치·타입·관계를 확인하기 전에는 추론기에 전달되지
않는다. 테스트에서는 ``CallableBackend``로 실제 모델을 불러오지 않고 같은
경계를 검증할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable


SCHEMA_VERSION = "semantic-state-v1"


class SemanticParseError(RuntimeError):
    pass


class CallableBackend:
    """테스트·오프라인 평가용 모델 대역. 반환값은 dict 또는 JSON 문자열이다."""
    model_id = "callable"

    def __init__(self, fn: Callable[[str], Any]):
        self.fn = fn

    def generate(self, text: str) -> Any:
        return self.fn(text)


class UnavailableBackend:
    """토큰 생성 모델 없이 동작하는 기본 경계.

    외부/토큰 모델 출력을 억지로 의미로 바꾸지 않는다. 이후 비토큰 기반
    의미 인식기가 준비되면 이와 동일한 ``generate`` 인터페이스로 연결한다.
    """
    model_id = "no-token-semantic-parser"

    def generate(self, _text: str) -> Any:
        raise SemanticParseError("토큰 기반 의미 모델은 이 런타임에서 사용하지 않습니다")


def _json_candidate(raw: Any) -> tuple[dict | None, str | None]:
    if isinstance(raw, dict):
        return raw, None
    text = str(raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None, "model_did_not_return_json"
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None, "invalid_model_json"
    return (value, None) if isinstance(value, dict) else (None, "model_json_not_object")


def _span(text: str, value: Any, location: str, rejected: list[dict]) -> dict | None:
    if not isinstance(value, dict):
        rejected.append({"location": location, "reason": "missing_evidence"})
        return None
    start, end, literal = value.get("start"), value.get("end"), value.get("text")
    if not isinstance(start, int) or not isinstance(end, int) or not isinstance(literal, str):
        rejected.append({"location": location, "reason": "invalid_evidence_type"})
        return None
    if start < 0 or end <= start or end > len(text) or text[start:end] != literal:
        rejected.append({"location": location, "reason": "evidence_not_exact", "evidence": value})
        return None
    return {"start": start, "end": end, "text": literal}


ALLOWED_INTENTS = {"question", "request", "dialogue", "unknown"}
ALLOWED_RELATIONS = {"arithmetic", "parallel_completion", "age_difference", "rank_overtake",
                     "co_moving_reference", "indivisible_process", "unitary_concept",
                     "before_after", "comparison"}
ALLOWED_QUERY_KINDS = {"value", "rank", "duration", "validity", "unknown"}


def validate(text: str, candidate: dict | None, *, model_id: str = "unknown") -> dict:
    """후보를 안전한 상태 JSON으로 축소한다. 기각한 값도 UI/평가에 남긴다."""
    base = {"schema": SCHEMA_VERSION, "model": model_id, "raw": text, "accepted": False,
            "intent": "unknown", "entities": [], "quantities": [], "relations": [],
            "query": None, "uncertainties": [], "rejected": []}
    if not isinstance(candidate, dict):
        base["uncertainties"].append("모델이 구조화된 의미 JSON을 만들지 못했습니다")
        return base
    intent = candidate.get("intent")
    if intent in ALLOWED_INTENTS:
        base["intent"] = intent
    else:
        base["rejected"].append({"location": "intent", "reason": "invalid_intent"})
    seen = set()
    for index, item in enumerate(candidate.get("entities") or []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("label"), str):
            base["rejected"].append({"location": "entities[%d]" % index, "reason": "invalid_entity"}); continue
        evidence = _span(text, item.get("evidence"), "entities[%d]" % index, base["rejected"])
        if evidence and item["id"] not in seen:
            seen.add(item["id"])
            base["entities"].append({"id": item["id"], "label": item["label"],
                                     "type": item.get("type") if isinstance(item.get("type"), str) else "unknown",
                                     "evidence": evidence})
    quantities = set()
    for index, item in enumerate(candidate.get("quantities") or []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or isinstance(item.get("value"), bool) or not isinstance(item.get("value"), (int, float)):
            base["rejected"].append({"location": "quantities[%d]" % index, "reason": "invalid_quantity"}); continue
        evidence = _span(text, item.get("evidence"), "quantities[%d]" % index, base["rejected"])
        if evidence and item["id"] not in quantities:
            quantities.add(item["id"])
            base["quantities"].append({"id": item["id"], "value": item["value"],
                                       "unit": item.get("unit") if isinstance(item.get("unit"), str) else None,
                                       "evidence": evidence})
    for index, item in enumerate(candidate.get("relations") or []):
        if not isinstance(item, dict) or item.get("type") not in ALLOWED_RELATIONS or not isinstance(item.get("args"), dict):
            base["rejected"].append({"location": "relations[%d]" % index, "reason": "invalid_relation"}); continue
        evidence = _span(text, item.get("evidence"), "relations[%d]" % index, base["rejected"])
        if evidence:
            base["relations"].append({"type": item["type"], "args": item["args"], "evidence": evidence})
    query = candidate.get("query")
    if isinstance(query, dict) and query.get("kind") in ALLOWED_QUERY_KINDS and isinstance(query.get("target"), str):
        evidence = _span(text, query.get("evidence"), "query", base["rejected"])
        if evidence:
            base["query"] = {"kind": query["kind"], "target": query["target"], "evidence": evidence}
    elif query is not None:
        base["rejected"].append({"location": "query", "reason": "invalid_query"})
    base["uncertainties"] = [x for x in (candidate.get("uncertainties") or []) if isinstance(x, str)][:12]
    base["accepted"] = bool(base["relations"] and base["query"] and base["intent"] == "question")
    if not base["accepted"]:
        base["uncertainties"].append("근거가 연결된 질문 상태가 충분하지 않습니다")
    return base


@dataclass
class SemanticParser:
    backend: Any = None

    def __post_init__(self):
        if self.backend is None:
            self.backend = UnavailableBackend()

    @property
    def model_id(self) -> str:
        return getattr(self.backend, "model_id", type(self.backend).__name__)

    def parse(self, text: str) -> dict:
        try:
            raw = self.backend.generate(text)
        except Exception as exc:
            result = validate(text, None, model_id=self.model_id)
            result["uncertainties"].append("의미 후보를 만들 수 없습니다: %s" % str(exc))
            return result
        candidate, error = _json_candidate(raw)
        result = validate(text, candidate, model_id=self.model_id)
        if error:
            result["uncertainties"].append(error)
        return result
