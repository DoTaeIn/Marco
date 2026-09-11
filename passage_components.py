# -*- coding: utf-8 -*-
"""발췌 문장 분류용 교체 부품.

문장 종류는 언어 문법 규칙으로 추측하지 않는다. 사람이 라벨한 자료를 우선
사용하고, 새 문장은 필요할 때만 별도 분류 부품에 맡긴다.
"""
from __future__ import annotations

import importlib
import os
from typing import Protocol


class PassageBackend(Protocol):
    def classify(self, text: str) -> list[str]: ...


class StatementFallback:
    component_id = "statement-fallback-v1"

    def classify(self, _text: str) -> list[str]:
        return ["진술"]


def resolve_backend(backend: PassageBackend | None = None) -> PassageBackend:
    if backend is not None:
        return backend
    spec = os.environ.get("NAI_PASSAGE_BACKEND", "")
    if not spec:
        return StatementFallback()
    module_name, separator, member_name = spec.partition(":")
    if not separator:
        raise ValueError("NAI_PASSAGE_BACKEND는 'module:Class' 또는 'module:factory' 형식이어야 합니다")
    component = getattr(importlib.import_module(module_name), member_name)
    instance = component() if callable(component) else component
    if not callable(getattr(instance, "classify", None)):
        raise TypeError("발췌 backend에는 classify(text) 메서드가 필요합니다")
    return instance
