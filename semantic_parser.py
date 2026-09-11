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
import re
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


class StructuralBackend:
    """토큰 생성 없이, 원문에 명시된 상태 관계만 후보 JSON으로 만든다.

    이 층은 답을 정하지 않는다. 숫자·관계·질문이 문장 안에 모두 드러난
    극히 좁은 경우만 `state_engine`의 KG 공리로 넘긴다. 패턴은 문제 이름이
    아니라 덧셈·순위·동시성 같은 상태 관계를 가리키며, 모호한 문장은
    `None`으로 돌려 기존의 정직한 미지 경계를 유지한다.
    """
    model_id = "local-structural-semantic-parser-v1"

    def __init__(self, model=None):
        self.model = model

    @staticmethod
    def _candidate(text: str, relation: str, args: dict, kind: str = "value") -> dict:
        # 전체 원문을 증거 span으로 둔다. 부분 발췌가 답의 근거를 숨기지 않고,
        # validate가 그 span을 다시 원문과 대조한다.
        evidence = {"start": 0, "end": len(text), "text": text}
        return {"intent": "question", "entities": [], "quantities": [],
                "relations": [{"type": relation, "args": args, "evidence": evidence}],
                "query": {"kind": kind, "target": "answer", "evidence": evidence},
                "uncertainties": []}

    def generate(self, text: str) -> Any:
        raw = str(text or "").strip()
        if not raw:
            return None
        from relational_semantics import RelationalParser
        parser = RelationalParser() if self.model is None else self.model.parser()
        relational = parser.parse(raw)
        if relational:
            return self._candidate(raw, "relational_graph", relational)
        import expression_graph
        expression = expression_graph.parse(raw) if self.model is None else self.model.parse_expression(raw)
        if expression:
            relation = "linear_equation" if len(expression["roots"]) == 2 else "arithmetic"
            return self._candidate(raw, relation, {"expression_graph": expression})
        # 한 미지수의 일차식은 숫자와 등식이 원문에 모두 있을 때만 상태로
        # 만든다. 뒤에 붙는 한국어 설명(예: "7이래")은 식의 일부가 아니므로
        # 허용하되, 다른 변수나 숫자가 바로 잇는 불완전한 식은 받지 않는다.
        compact = re.sub(r"\s+", "", raw)
        linear = re.search(
            r"(?<![0-9A-Za-z])(?P<coefficient>[+-]?\d*)[xX]"
            r"(?P<sign>[+-])(?P<constant>\d+)=(?P<right>[+-]?\d+)(?![0-9xX])",
            compact,
        )
        if linear:
            coefficient_text = linear.group("coefficient")
            coefficient = {"": 1, "+": 1, "-": -1}.get(coefficient_text)
            if coefficient is None:
                coefficient = int(coefficient_text)
            constant = int(linear.group("constant"))
            if linear.group("sign") == "-":
                constant = -constant
            return self._candidate(raw, "linear_equation", {
                "variable": "x", "coefficient": coefficient,
                "constant": constant, "right": int(linear.group("right")),
            })
        # 명시적인 사칙연산. `7과 5를 더한 값`도 `1 더하기 1`도 같은
        # 산술 상태로 수렴한다. 단위·변수·문맥이 섞인 식은 만들지 않는다.
        add = (re.search(r"(?<!\d)(\d+)\s*(?:더하기|\+)\s*(\d+)(?!\d)", raw)
               or re.search(r"(?<!\d)(\d+)\s*(?:과|와)\s*(\d+)\s*(?:을|를)?\s*더", raw))
        if add:
            return self._candidate(raw, "arithmetic", {"operator": "+", "left": int(add.group(1)), "right": int(add.group(2))})
        sub = re.search(r"(?<!\d)(\d+)\s*(?:빼기|-)\s*(\d+)(?!\d)", raw)
        if sub:
            return self._candidate(raw, "arithmetic", {"operator": "-", "left": int(sub.group(1)), "right": int(sub.group(2))})
        multiply = re.search(r"(?<!\d)(\d+)\s*(?:곱하기|×|\*)\s*(\d+)(?!\d)", raw)
        if multiply:
            return self._candidate(raw, "arithmetic", {"operator": "*", "left": int(multiply.group(1)), "right": int(multiply.group(2))})
        divide = re.search(r"(?<!\d)(\d+)\s*(?:나누기|÷|/)\s*(\d+)(?!\d)", raw)
        if divide:
            return self._candidate(raw, "arithmetic", {"operator": "/", "left": int(divide.group(1)), "right": int(divide.group(2))})
        # 한 사람을 앞질렀다면 그 사람이 있던 순위로 이동한다. 실제 순위
        # 숫자가 없으면 절대 추정하지 않는다.
        rank = re.search(r"(\d+)\s*(?:등|위)(?:\s*(?:선수|주자|인\s*사람))?\s*(?:을|를)?\s*(?:추월|앞질)", raw)
        if rank:
            return self._candidate(raw, "rank_overtake", {"overtaken_rank": int(rank.group(1))}, "rank")
        # 동시성과 독립성, 한 작업의 명시 기간이 모두 있을 때만 병렬 완료다.
        parallel = re.search(r"(\d+)\s*(시간|분|초|일|개월)", raw)
        if parallel and re.search(r"독립", raw) and re.search(r"동시|함께", raw):
            return self._candidate(raw, "parallel_completion", {"duration": int(parallel.group(1)), "unit": parallel.group(2), "simultaneous": True, "independent": True}, "duration")
        # 함께 뜨는 배와 사다리의 상대 기준틀. 배·사다리·수위 변화·칸 수가
        # 모두 있는 경우에만 적용한다.
        visible = re.search(r"(\d+)\s*칸", raw)
        if visible and re.search(r"배", raw) and re.search(r"사다리", raw) and re.search(r"수면|수위|물", raw) and re.search(r"오르|높아|올라", raw):
            return self._candidate(raw, "co_moving_reference", {"visible_count": int(visible.group(1)), "same_reference_frame": True}, "value")
        # 완결 단위의 분수 전제. 단위 이름은 공리 그래프가 검증한다.
        unitary = re.search(r"반쪽(?:짜리)?\s*([가-힣]+)", raw)
        if unitary:
            concept = re.sub(r"(?:은|는|이|가|을|를)$", "", unitary.group(1))
            return self._candidate(raw, "unitary_concept", {"concept": concept, "fractional_premise": True}, "validity")
        # 두 시점의 나이와 '절반'이 모두 명시된 경우에만 일정한 나이 차를
        # 만들 수 있다. 나이와 사람이 빠진 문장은 후보를 만들지 않는다.
        ages = [int(x) for x in re.findall(r"(\d+)\s*살", raw)]
        if len(ages) >= 2 and re.search(r"절반", raw) and re.search(r"동생|형|누나|언니|오빠", raw):
            first, later = ages[0], ages[-1]
            if first % 2 == 0 and later >= first:
                return self._candidate(raw, "age_difference", {"later_age": later, "age_difference": first - first // 2}, "value")
        # 단일 임신·출산 과정의 기간은 사람 수를 더해도 병렬화하지 않는다.
        months = re.search(r"(\d+)\s*개월", raw)
        if months and re.search(r"임신|출산", raw) and re.search(r"아이\s*1\s*명|한\s*명", raw):
            return self._candidate(raw, "indivisible_process", {"process": "임신출산", "duration": int(months.group(1)), "unit": "개월", "single_output": True}, "duration")
        return None


# 후보가 없는 까닭을 사람이 읽을 말로 적는다. 기계 코드는 기록·평가용으로
# `reason`에 남기고, 화면에는 이 문장을 보인다.
#
# `no_state_relation`을 따로 두는 이유가 이 표의 전부다. 구조 해석기는 문장에
# 상태 관계가 없으면 정상적으로 아무것도 안 돌려주는데, 그것을 `없음 -> JSON
# 아님`으로 뭉뚱그려 "모델이 JSON을 못 만들었다"고 적고 있었다. 여기에는 부를
# 모델이 없다. 없는 모델을 탓하면 읽는 사람이 원인을 못 찾는다.
REASON_TEXT = {
    "no_state_relation": "이 문장에서 계산할 상태 관계를 찾지 못했습니다 — 구조 해석기는 수·순위·기간처럼 원문에 드러난 관계만 다룹니다",
    "empty_output": "해석기가 빈 출력을 냈습니다",
    "not_json": "해석기 출력에 상태 JSON이 없습니다",
    "invalid_json": "해석기 출력이 올바른 JSON이 아닙니다",
    "json_not_object": "해석기 출력이 JSON 객체가 아닙니다",
}


def _json_candidate(raw: Any) -> tuple[dict | None, str | None]:
    if isinstance(raw, dict):
        return raw, None
    if raw is None:
        return None, "no_state_relation"
    text = str(raw).strip()
    if not text:
        return None, "empty_output"
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None, "not_json"
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None, "invalid_json"
    return (value, None) if isinstance(value, dict) else (None, "json_not_object")


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
                     "linear_equation", "relational_graph", "before_after", "comparison"}
ALLOWED_QUERY_KINDS = {"value", "rank", "duration", "validity", "unknown"}


def validate(text: str, candidate: dict | None, *, model_id: str = "unknown",
             reason: str | None = None) -> dict:
    """후보를 안전한 상태 JSON으로 축소한다. 기각한 값도 UI/평가에 남긴다.

    `reason`은 후보가 없을 때 그 까닭을 가리키는 기계 코드다(`REASON_TEXT`).
    화면에는 그 코드가 아니라 짝지은 문장을 보인다."""
    base = {"schema": SCHEMA_VERSION, "model": model_id, "raw": text, "accepted": False,
            "intent": "unknown", "entities": [], "quantities": [], "relations": [],
            "query": None, "uncertainties": [], "rejected": [], "reason": None}
    if not isinstance(candidate, dict):
        base["reason"] = reason or "no_candidate"
        base["uncertainties"].append(REASON_TEXT.get(base["reason"], "검증할 의미 후보가 없습니다"))
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
        base["reason"] = "incomplete_state"
        base["uncertainties"].append("원문 근거가 붙은 질문 상태가 아직 덜 찼습니다")
    return base


@dataclass
class SemanticParser:
    backend: Any = None
    model: Any = None

    def __post_init__(self):
        if self.backend is None:
            self.backend = StructuralBackend(self.model)

    @property
    def model_id(self) -> str:
        return getattr(self.backend, "model_id", type(self.backend).__name__)

    def parse(self, text: str) -> dict:
        try:
            raw = self.backend.generate(text)
        except Exception as exc:
            result = validate(text, None, model_id=self.model_id, reason="backend_error")
            result["uncertainties"] = ["의미 후보를 만들 수 없습니다: %s" % str(exc)]
            return result
        candidate, error = _json_candidate(raw)
        # 까닭은 화면에 문장 한 줄로만 나간다. 같은 말을 코드로 한 번 더 붙이면
        # 읽는 사람에게는 '불확실성 2건'이 되고, 그 둘이 같은 사실이다.
        return validate(text, candidate, model_id=self.model_id, reason=error)
