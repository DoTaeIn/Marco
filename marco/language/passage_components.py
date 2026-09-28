# -*- coding: utf-8 -*-
"""발췌 문장 분류용 교체 부품.

문장 종류는 언어 문법 규칙으로 추측하지 않는다. 사람이 라벨한 자료를 우선
사용하고, 새 문장은 필요할 때만 별도 분류 부품에 맡긴다.

**어느 부품을 쓸지는 팩이 정한다.** 예전에는 `NAI_PASSAGE_BACKEND` 환경변수로
골랐는데, 그러면 한 실행 안에서 팩마다 다르게 고를 수가 없고 팩을 둘 띄우면
나중에 켠 쪽이 앞엣것의 선택을 덮는다. 이제 `PackModel.component` 한 곳을 본다.
"""
from __future__ import annotations

from typing import Protocol

KIND = "발췌분류"


class PassageBackend(Protocol):
    def classify(self, text: str) -> list[str]: ...


class StatementFallback:
    """고른 부품이 없을 때. 근거 없이 꼴을 단정하지 않는다."""
    component_id = "statement-fallback-v1"

    def classify(self, _text: str) -> list[str]:
        return ["진술"]


def resolve_backend(backend: PassageBackend | None = None, model=None) -> PassageBackend:
    """주입 > 팩 선언 > 기본. 고른 것만 불러온다."""
    if backend is None and model is not None:
        backend = model.component(KIND)
    if backend is None:
        return StatementFallback()
    if not callable(getattr(backend, "classify", None)):
        raise TypeError("발췌 backend에는 classify(text) 메서드가 필요합니다")
    return backend
