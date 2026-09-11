"""세션 한정 정서 표현 상태.

이 모듈은 사람의 마음을 진단하거나 시스템이 의식을 가졌다고 주장하지 않는다.
사용자가 직접 쓴 정서 표현과 대화의 안전 신호만 받아, 답변의 *표현 방식*을
일관되게 조절한다. 사실 판정·KG 선택·계획·승인에는 영향을 주지 않는다.
"""
from __future__ import annotations

from copy import deepcopy

from language_components import load_language_pack

DEFAULT = {
    "enabled": False,
    "mode": "neutral",
    "turn": 0,
    "signals": [],
    "note": "정서 표현은 꺼져 있습니다.",
}


def initial(enabled: bool = False) -> dict:
    state = deepcopy(DEFAULT)
    state["enabled"] = bool(enabled)
    if state["enabled"]:
        state["note"] = "정서 표현을 켰습니다. 사실 판단은 바뀌지 않습니다."
    return state


def update(previous: dict | None, text: str, enabled: bool | None = None, *, language: str | None = None, language_pack: dict | None = None) -> dict:
    """원문에 있는 신호만으로 표현 모드를 고른다.

    ``signals``는 사용자 내면에 대한 판정이 아니라, 매칭된 원문 표지의 설명이다.
    """
    state = initial() if not previous else deepcopy(previous)
    if enabled is not None:
        state["enabled"] = bool(enabled)
    state["turn"] = int(state.get("turn", 0)) + 1
    if not state["enabled"]:
        state.update({"mode": "neutral", "signals": [], "note": "정서 표현은 꺼져 있습니다."})
        return state

    pack = load_language_pack(language) if language_pack is None else language_pack
    affect = pack["conversation"].get("affect") or {}
    raw = str(text or "")
    mode, note, signals = "focus", affect.get("focus_note", ""), []
    for item in affect.get("signals") or []:
        phrases = item.get("phrases") if isinstance(item, dict) else []
        if isinstance(phrases, list) and any(isinstance(phrase, str) and phrase in raw for phrase in phrases):
            mode, note = item.get("mode", "focus"), item.get("note", "")
            signal = item.get("signal")
            signals = [signal] if isinstance(signal, str) else []
            break
    state.update({"mode": mode, "signals": signals, "note": note})
    return state


def decorate(answer: str, state: dict | None, *, language: str | None = None, language_pack: dict | None = None) -> str:
    """검증된 답의 앞에 짧은 표현만 더한다. 답 내용은 변경하지 않는다."""
    if not state or not state.get("enabled"):
        return answer
    pack = load_language_pack(language) if language_pack is None else language_pack
    affect = pack["conversation"].get("affect") or {}
    prefix = (affect.get("prefixes") or {}).get(state.get("mode"), "")
    return prefix + answer if prefix else answer
