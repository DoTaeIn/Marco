"""검증된 근거에서 답의 재료를 고르고, 표현은 작게 조립한다.

이 모듈은 새 사실이나 비교 결론을 만들지 않는다. 호출자는 이미 확인한 문장과
출처만 넘기고, 결과의 ``selected``로 실제 출력이 어느 근거를 썼는지 남긴다.
"""
from __future__ import annotations


def _item(raw):
    """근거 하나의 안전한 표현·구조 부분을 나눈다.

    `text`는 사용자에게 보일 원문이고, `relation`·`attributes`·`depends_on`은
    팩이 검증해 둔 구조다. 이 함수는 한국어 문장에서 관계를 새로 추측하지
    않는다.
    """
    if not isinstance(raw, dict):
        return None
    text, source = str(raw.get("text") or "").strip(), str(raw.get("source") or "").strip()
    if not text or not source:
        return None
    relation = str(raw.get("relation") or "").strip()
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    attributes = {str(key).strip(): str(value).strip() for key, value in attributes.items()
                  if str(key).strip() and str(value).strip()}
    depends = raw.get("depends_on", [])
    depends = [str(value) for value in depends] if isinstance(depends, list) else []
    achieves = raw.get("achieves", raw.get("달성", []))
    achieves = [str(value).strip() for value in achieves] if isinstance(achieves, list) else []
    def state_rows(value):
        if not isinstance(value, list):
            return []
        return [tuple(str(part).strip() for part in row)
                for row in value if isinstance(row, (list, tuple)) and len(row) == 3
                and all(str(part).strip() for part in row)]
    requires_state = state_rows(raw.get("requires_state", raw.get("상태전제", [])))
    effects = state_rows(raw.get("effects", raw.get("결과상태", [])))
    return {"text": text, "source": source, "relation": relation,
            "attributes": attributes, "id": str(raw.get("id") or ""),
            "depends_on": depends, "achieves": achieves, "requires_state": requires_state,
            "effects": effects,
            "actionable": bool(raw.get("actionable", False))}


def _select(evidence, *, actionable=False, relation=None, limit=3, diversify=False):
    candidates, seen = [], set()
    for raw in evidence or []:
        item = _item(raw)
        if item is None or (item["text"], item["source"]) in seen:
            continue
        if actionable and not item["actionable"]:
            continue
        if relation is not None and item["relation"] not in relation:
            continue
        candidates.append(item)
        seen.add((item["text"], item["source"]))
    if not diversify:
        return candidates[:limit]
    # 요약의 앞자리를 한 출처의 문장으로 모두 채우면, 이미 확보한 다중 근거를
    # 실제 답에서 버리게 된다. 출처마다 첫 문장을 먼저 쓰되, 근거가 한 곳뿐인
    # 경우나 상한이 남으면 원래 순서의 나머지를 계속 쓴다.
    selected, sources = [], set()
    for item in candidates:
        if item["source"] not in sources:
            selected.append(item)
            sources.add(item["source"])
            if len(selected) == limit:
                return selected
    for item in candidates:
        if item not in selected:
            selected.append(item)
            if len(selected) == limit:
                break
    return selected


def _ordered_steps(items):
    """팩이 선언한 선행조건만 따라, 순환이면 계획을 만들지 않는다."""
    ids = {item["id"]: item for item in items if item["id"]}
    if any(dep not in ids for item in items for dep in item["depends_on"]):
        return None
    ordered, pending = [], list(items)
    while pending:
        available = [item for item in pending
                     if all(dep in {done["id"] for done in ordered} for dep in item["depends_on"])]
        if not available:
            return None
        for item in available:
            ordered.append(item)
            pending.remove(item)
    return ordered


def _goal_steps(evidence, goal, state, limit):
    """선언한 목표를 달성하는 행동과 그 선행 행동만 고른다.

    목표·전제·행동의 연결은 근거 자산에 있고, 이 함수는 이름을 모른 채
    의존 그래프와 현재 상태만 계산한다. 목표 행동이 없거나 필요한 상태가
    확인되지 않으면 일부 단계를 그럴듯한 계획으로 내보내지 않는다.
    """
    actions = _select(evidence, actionable=True, limit=8)
    if not any(item["achieves"] for item in actions):
        return None  # 기존 선언에는 목표 연결이 없으므로 이전 경로가 쓴다.
    requested = str(goal or "").strip()
    target = [item for item in actions
              if any(requested and (requested in achieved or achieved in requested)
                     for achieved in item["achieves"])]
    if not target:
        return []
    by_id = {item["id"]: item for item in actions if item["id"]}
    facts = {tuple(str(value).strip() for value in row)
             for row in (state or []) if isinstance(row, (list, tuple)) and len(row) == 3}
    selected, visiting = {}, set()

    def include(item):
        """행동의 선언 전제는 현재 사실 또는 단 하나의 결과 행동으로만 채운다."""
        item_id = item["id"]
        if not item_id or item_id in visiting:
            return False
        if item_id in selected:
            return True
        visiting.add(item_id)
        selected[item_id] = item
        for dep in item["depends_on"]:
            if dep not in by_id or not include(by_id[dep]):
                return False
        for requirement in item["requires_state"]:
            if requirement in facts:
                continue
            producers = [candidate for candidate in actions
                         if candidate["id"] != item_id and requirement in candidate["effects"]]
            # 여러 행동이 같은 결과를 낸다면 현재 근거만으로 하나를 고르지 않는다.
            if len(producers) != 1 or not include(producers[0]):
                return False
        visiting.remove(item_id)
        return True

    if not all(include(item) for item in target):
        return []
    # 선행 의존성뿐 아니라 앞 행동이 낸 상태를 적용하며 순서를 찾는다. 결과 상태는
    # 같은 대상·관계의 이전 값을 대체하는 선언적 상태 변화다.
    ordered, remaining, available_facts = [], dict(selected), set(facts)
    while remaining:
        next_item = next((item for item in remaining.values()
                          if all(dep in {done["id"] for done in ordered}
                                 for dep in item["depends_on"])
                          and all(requirement in available_facts
                                  for requirement in item["requires_state"])), None)
        if next_item is None:
            return []
        ordered.append(next_item)
        del remaining[next_item["id"]]
        for effect in next_item["effects"]:
            available_facts = {fact for fact in available_facts if fact[:2] != effect[:2]}
            available_facts.add(effect)
    return ordered if len(ordered) <= limit else []


def _causal_chain(evidence, limit):
    """선언된 원인→결과 의존 사슬 하나만 설명으로 낸다.

    ``cause``와 ``effect``라는 꼬리표가 같은 자료에 있다는 사실만으로 둘을
    잇지 않는다. 결과가 의존하는 항목을 따라가 원인에 닿을 때에만 순서를
    가진 설명 재료가 된다.
    """
    items = _select(evidence, relation={"cause", "effect"}, limit=8)
    by_id = {item["id"]: item for item in items if item["id"]}
    for effect in items:
        if effect["relation"] != "effect" or not effect["id"]:
            continue
        chosen, pending = {}, list(effect["depends_on"])
        while pending:
            item_id = pending.pop()
            item = by_id.get(item_id)
            if item is None or item_id in chosen:
                continue
            chosen[item_id] = item
            pending.extend(item["depends_on"])
        if not any(item["relation"] == "cause" for item in chosen.values()):
            continue
        chain = _ordered_steps(list(chosen.values()) + [effect])
        if chain is not None and len(chain) <= limit:
            return chain
    return None


def compose(kind, evidence, *, limit=3, goal=None, state=None):
    """근거 문장을 제한된 수만 선택해 요약·설명·계획 답으로 낸다.

    ``evidence``의 각 원소는 ``text``와 ``source``를 가져야 한다. 빈 문장,
    출처 없는 문장, 또는 상한 밖의 문장은 출력하지 않는다. 요약은 추출식이다.
    그러므로 원인·우선순위·효과를 임의로 덧붙이지 않는다.
    """
    if kind not in {"request.summary", "request.explain", "request.plan"}:
        raise ValueError("unsupported_grounded_response")
    if not isinstance(limit, int) or not 1 <= limit <= 8:
        raise ValueError("invalid_response_limit")
    if kind == "request.explain":
        # 꼬리표가 아니라 결과에서 원인으로 가는 선언된 의존선이 있어야 한다.
        # 연결이 없으면 두 문장을 억지로 인과로 바꾸지 않고 추출식으로 남긴다.
        selected = _causal_chain(evidence, limit)
        mode = "grounded_causal_explanation" if selected else "extractive_grounded_response"
        if selected is None:
            selected = _select(evidence, limit=limit)
    elif kind == "request.plan":
        selected = _goal_steps(evidence, goal, state, limit)
        if selected is None:
            selected = _select(evidence, actionable=True, limit=limit)
            selected = _ordered_steps(selected) if selected else []
        mode = "grounded_dependency_plan"
    else:
        selected = _select(evidence, limit=limit, diversify=True)
        mode = "extractive_grounded_response"
    if not selected:
        return None
    if kind == "request.plan":
        answer = "\n".join("%d. %s" % (index, item["text"])
                           for index, item in enumerate(selected, 1))
    else:
        answer = "\n".join("- %s" % item["text"] for item in selected)
    return {"kind": kind, "answer": answer,
            "selected": [{"text": item["text"], "source": item["source"]} for item in selected],
            "mode": mode}


def compare(entries):
    """공통 속성이 인증됐을 때만 속성별 비교를 만들고, 아니면 원문을 병렬한다."""
    selected, seen = [], set()
    for item in entries or []:
        shaped = _item(item)
        if not isinstance(item, dict) or shaped is None:
            continue
        label, text, source = (str(item.get(key) or "").strip()
                               for key in ("label", "text", "source"))
        if not label or not text or not source or (label, text, source) in seen:
            continue
        selected.append({"label": label, "text": text, "source": source,
                         "attributes": shaped["attributes"]})
        seen.add((label, text, source))
        if len(selected) == 2:
            break
    if len(selected) != 2:
        return None
    attributes = set(selected[0].get("attributes", {})) & set(selected[1].get("attributes", {}))
    differing = [key for key in sorted(attributes)
                 if selected[0]["attributes"][key] != selected[1]["attributes"][key]]
    if differing:
        answer = "\n\n".join("**%s**\n- %s: %s\n- %s: %s" %
                              (key, selected[0]["label"], selected[0]["attributes"][key],
                               selected[1]["label"], selected[1]["attributes"][key])
                              for key in differing)
        mode = "grounded_attribute_comparison"
    else:
        answer = "\n\n".join("**%s** — %s" % (item["label"], item["text"])
                              for item in selected)
        mode = "grounded_comparison"
    return {"kind": "request.compare",
            "answer": answer, "selected": selected, "mode": mode}
