# -*- coding: utf-8 -*-
"""교체 가능한 대화 언어 팩과 가장 작은 기본 해석 부품.

코어는 특정 언어의 낱말, 조사, 정규식을 알지 않는다. 언어 팩의 선언형
템플릿을 읽어 구조화된 후보를 만들 뿐이며, 더 좋은 모델은 같은 ``parse``
인터페이스를 구현해 주입할 수 있다.
"""
from __future__ import annotations

import json
import os
import importlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent


class DialogueBackend(Protocol):
    def parse(self, text: str, pack: dict[str, Any]) -> dict[str, Any] | None: ...


def _language_path(language: str | None = None) -> Path:
    name = language or os.environ.get("NAI_LANGUAGE") or os.environ.get("KG_LANG") or "한국어"
    path = Path(name)
    if path.suffix.lower() != ".json":
        path = ROOT / "styles" / (name + ".json")
    elif not path.is_absolute():
        path = ROOT / path
    return path


def _validate_clauses(clauses):
    if not isinstance(clauses, dict):
        raise ValueError("문장분리 must be an object")
    for key in ("candidate_suffixes", "continuation_prefixes", "comma_after_suffixes", "question_marks"):
        values = clauses.get(key, [])
        if not isinstance(values, list) or not all(isinstance(x, str) and x for x in values):
            raise ValueError("문장분리.%s must contain nonempty strings" % key)
    rules = clauses.get("canonical_endings", [])
    if not isinstance(rules, list):
        raise ValueError("문장분리.canonical_endings must be a list")
    ids = set()
    for rule in rules:
        if (not isinstance(rule, dict)
                or not isinstance(rule.get("id"), str) or not rule["id"] or rule["id"] in ids
                or not isinstance(rule.get("suffix"), str) or not rule["suffix"]
                or not isinstance(rule.get("replacements"), list) or not rule["replacements"]
                or not all(isinstance(x, str) for x in rule["replacements"])
                or not isinstance(rule.get("example_features", {}), dict)):
            raise ValueError("invalid 문장분리.canonical_endings rule")
        ids.add(rule["id"])
    return clauses


@lru_cache(maxsize=8)
def _cached_reasoning_language(path, stamp, size):
    with Path(path).open(encoding="utf-8") as handle:
        pack = json.load(handle)
    return {"clauses": _validate_clauses(pack.get("문장분리", {})),
            "inflection": pack.get("활용", {})}


def load_clause_grammar(language: str | None = None) -> dict[str, Any]:
    """Read the selected style's optional clause rules, including legacy styles.

    The cache follows file revisions, not just the selected name. An absent
    clause section is empty; it never inherits Korean rules from another file.
    """
    return load_reasoning_language(language)["clauses"]


def load_reasoning_language(language: str | None = None) -> dict[str, Any]:
    """Only the optional components needed for symbolic language analysis."""
    path = _language_path(language)
    stat = path.stat()
    return _cached_reasoning_language(str(path), stat.st_mtime_ns, stat.st_size)


def load_language_pack(language: str | None = None) -> dict[str, Any]:
    """언어 이름 또는 JSON 경로 하나로 대화 설정을 읽는다."""
    path = _language_path(language)
    with path.open(encoding="utf-8") as handle:
        pack = json.load(handle)
    return decode_language_pack(pack, str(path))


def decode_language_pack(pack: dict, source: str = "") -> dict[str, Any]:
    """Decode in-memory pack content. Never consult paths or environment here."""
    path = Path(source)
    conversation = pack.get("대화이해", pack.get("conversation", {}))
    if not isinstance(conversation, dict):
        raise ValueError("언어 팩에 '대화이해' 또는 'conversation' 객체가 필요합니다: %s" % path)
    shell_risks = conversation.get("shell_risks", {})
    if not isinstance(shell_risks, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                                    for key, value in shell_risks.items()):
        raise ValueError("언어 팩의 shell_risks는 문자열 → 문자열 객체여야 합니다: %s" % path)
    templates = conversation.get("templates", [])
    if not isinstance(templates, list):
        raise ValueError("언어 팩의 templates는 목록이어야 합니다: %s" % path)
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError("언어 팩의 template 항목은 객체여야 합니다: %s" % path)
        types = item.get("slot_types", {})
        if not isinstance(types, dict) or not all(isinstance(key, str) and value in {"text", "integer"}
                                                   for key, value in types.items()):
            raise ValueError("언어 팩의 slot_types는 슬롯 이름과 text/integer 타입의 객체여야 합니다: %s" % path)
    return {"name": pack.get("이름") or pack.get("name") or path.stem,
            "path": str(path), "conversation": conversation,
            "clauses": _validate_clauses(pack.get("문장분리", {})),
            "inflection": pack.get("활용", {}),
            "relations": pack.get("관계해석", {}),
            "verbal_expressions": pack.get("말수식", {}),
            "output_contracts": pack.get("출력계약", {}),
            "state_answers": pack.get("상태표현", {})}


def _template_match(text: str, template: str, slot_types: dict[str, str] | None = None) -> dict[str, str] | None:
    """언어 팩의 슬롯 타입을 지키며 선언형 템플릿을 캡처한다."""
    pieces: list[tuple[str, str | None]] = []
    cursor = 0
    while cursor < len(template):
        opening = template.find("{", cursor)
        if opening < 0:
            pieces.append((template[cursor:], None)); break
        if opening > cursor:
            pieces.append((template[cursor:opening], None))
        closing = template.find("}", opening + 1)
        if closing < 0:
            return None
        slot = template[opening + 1:closing].strip()
        if not slot:
            return None
        pieces.append(("", slot)); cursor = closing + 1
    if not pieces:
        return None
    types = slot_types or {}

    def match(index: int, position: int, values: dict[str, str]) -> dict[str, str] | None:
        if index == len(pieces):
            return values if position == len(text) else None
        literal, slot = pieces[index]
        if slot is None:
            return match(index + 1, position + len(literal), values) if text.startswith(literal, position) else None
        # 다음 고정 조각의 모든 위치를 시도한다. `{a} {b}`처럼 공백이 여러 번
        # 나오는 언어에서도 뒤쪽 슬롯까지 맞는 해석만 선택한다.
        next_literal = next((value for value, next_slot in pieces[index + 1:] if next_slot is None and value), "")
        ends = [len(text)] if not next_literal else []
        if next_literal:
            cursor = position
            while True:
                cursor = text.find(next_literal, cursor)
                if cursor < 0:
                    break
                ends.append(cursor); cursor += 1
        for end in ends:
            value = text[position:end].strip()
            if not value:
                continue
            if types.get(slot) == "integer" and not value.isdecimal():
                continue
            result = match(index + 1, end, {**values, slot: value})
            if result is not None:
                return result
        return None
    return match(0, 0, {})


class TemplateBackend:
    """의존성 없는 기본 부품. 모든 언어 지식은 팩의 템플릿에 있다."""
    component_id = "template-language-pack-v1"

    def parse(self, text: str, pack: dict[str, Any]) -> dict[str, Any] | None:
        templates = pack.get("conversation", {}).get("templates") or []
        best: tuple[int, dict[str, Any]] | None = None
        for item in templates:
            if not isinstance(item, dict) or not isinstance(item.get("template"), str):
                continue
            slots = _template_match(text, item["template"], item.get("slot_types"))
            if slots is None:
                continue
            literal_size = len(item["template"]) - sum(len(key) + 2 for key in slots)
            candidate = dict(item.get("result") or {})
            candidate["slots"], candidate["evidence"] = slots, [item["template"]]
            if best is None or literal_size > best[0]:
                best = (literal_size, candidate)
        for item in pack.get("conversation", {}).get("phrases") or []:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or item["text"] != text:
                continue
            candidate = dict(item.get("result") or {})
            candidate["slots"], candidate["evidence"] = {}, [item["text"]]
            if best is None or len(item["text"]) > best[0]:
                best = (len(item["text"]), candidate)
        return best[1] if best else None


def resolve_backend(backend: DialogueBackend | None = None, pack: dict[str, Any] | None = None) -> DialogueBackend:
    """명시 주입이 우선이며, 그 밖에는 언어 팩이 고른 부품을 불러온다.

    ``backend`` 값은 ``module:Class`` 또는 ``module:factory`` 형식이다. factory는
    인자 없이 backend를 반환해야 한다. 팩에 지정하지 않으면 의존성 없는 기본
    템플릿 부품을 쓴다.
    """
    if backend is not None:
        return backend
    spec = ((pack or {}).get("conversation", {}).get("backend"))
    if not isinstance(spec, str) or not spec:
        return TemplateBackend()
    module_name, separator, member_name = spec.partition(":")
    if not separator or not module_name or not member_name:
        raise ValueError("대화 backend는 'module:Class' 또는 'module:factory' 형식이어야 합니다")
    component = getattr(importlib.import_module(module_name), member_name)
    instance = component() if callable(component) else component
    if not callable(getattr(instance, "parse", None)):
        raise TypeError("대화 backend에는 parse(text, pack) 메서드가 필요합니다")
    return instance
