# -*- coding: utf-8 -*-
"""언어 팩과 교체 가능한 부품으로 사용자 발화를 구조화한다.

자연어 해석은 ``language_components.DialogueBackend``가 맡는다. 이 코어는
언어와 무관한 세션 문맥, JSON 모양, URL/명령 안전성만 처리한다.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from language_components import DialogueBackend, load_language_pack, resolve_backend

SHELL_HEAD = re.compile(r"^\s*(?:[$#]\s*)?([A-Za-z][A-Za-z0-9_-]*)\b")
URL = re.compile(r"https?://[^\s<>]+", re.I)
PATH = re.compile(r"(?:\.?\.?/|/)[\w.\-~/]+|\b[\w.-]+\.(?:py|js|ts|json|md|txt|csv|html|css|kg|kgpack)(?=$|[\s,;:)\]}>\"']|[이가을를은는에의로])", re.I)
def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or "")).replace("\u200b", "").strip()


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"```.*?```|`[^`\n]+`|https?://[^\s<>]+", text, re.S | re.I)]


def split_segments(text: str) -> list[str]:
    ranges = _protected_ranges(text)
    def protected(index: int) -> bool:
        return any(start <= index < end for start, end in ranges)
    start, output = 0, []
    for index, char in enumerate(text):
        if protected(index):
            continue
        if char in "\n;" or (char in ".!?。！？" and (index + 1 == len(text) or text[index + 1].isspace())):
            if text[start:index].strip():
                output.append(text[start:index + 1].strip(" \t\r\n,;:"))
            start = index + 1
    if text[start:].strip():
        output.append(text[start:].strip(" \t\r\n,;:"))
    return output or ([text] if text else [])


def _command(text: str, semantic: dict[str, Any], shell_risks: dict[str, str]) -> dict:
    head = SHELL_HEAD.match(text)
    risk, evidence = None, []
    explicit_shell = text.lstrip().startswith(("$", "#"))
    if head and (explicit_shell or head.group(1).lower() in shell_risks):
        risk, evidence = shell_risks.get(head.group(1).lower(), "credential_or_unknown"), ["shell-protocol"]
    declared = semantic.get("command") if isinstance(semantic, dict) else None
    if isinstance(declared, dict) and declared.get("risk") in {"read", "write", "destructive", "external", "credential_or_unknown"}:
        risk = declared["risk"]
        evidence.extend(semantic.get("evidence") or [])
    if not risk:
        return {"present": False, "syntax": None, "risk": "none", "evidence": [], "execution_allowed": False}
    return {"present": True, "syntax": "shell_like" if head else "natural_language", "risk": risk, "evidence": list(dict.fromkeys(evidence)), "execution_allowed": False}


def _context(text: str, history: list[dict], refs: list[str]) -> tuple[list[dict], list[str]]:
    found = [ref for ref in refs if ref and ref in text]
    if not found:
        return [], []
    candidates = []
    for age, item in enumerate(reversed(history[-12:]), 1):
        for segment in item.get("segments", []):
            for subject in segment.get("subject_candidates", []):
                if subject.get("source") == "current" and subject.get("text"):
                    candidates.append({"text": subject["text"], "turns_ago": age, "confidence": round(max(.35, .84 - .06 * (age - 1)), 2)})
    unique = []
    for candidate in candidates:
        if candidate["text"] not in {item["text"] for item in unique}:
            unique.append(candidate)
    if not unique:
        return [{"text": ref, "resolved_to": None, "confidence": 0, "reason": "session_has_no_prior_subject"} for ref in found], ["context.no_history"]
    return [{"text": ref, "resolved_to": unique[0]["text"], "confidence": unique[0]["confidence"], "alternatives": unique[1:3], "reason": "recent_session_subject"} for ref in found], ["context.session"]


def _goal(segment: dict) -> dict:
    acts = [item["kind"] for item in segment["act_candidates"]]
    subject = next((item for item in segment["subject_candidates"] if item["source"] in ("context", "current")), None)
    kind = "perform" if segment["command"]["present"] else ("inform" if any(a.startswith("request.") for a in acts) else "clarify")
    return {"kind": kind, "subject": subject["text"] if subject else None, "requested_actions": acts, "risk": segment["command"]["risk"], "output": "action_result" if kind == "perform" else "grounded_answer"}


def _has_text(text: str) -> bool:
    return any(char.isalnum() for char in text)


def understand(raw: str, history: list[dict] | None = None, *, language: str | None = None, backend: DialogueBackend | None = None, language_pack: dict | None = None) -> dict:
    """언어 팩 하나와 backend 하나만 주입해 같은 schema를 얻는다."""
    raw, history = str(raw or ""), list(history or [])
    normalized = normalize(raw)
    if not normalized:
        raise ValueError("입력이 비어 있습니다")
    pack = load_language_pack(language) if language_pack is None else language_pack
    parser = resolve_backend(backend, pack)
    conversation = pack["conversation"]
    segments, traces, unknown = [], [], []
    for raw_segment in split_segments(raw):
        text = normalize(raw_segment)
        semantic = parser.parse(text, pack) or {}
        intent = semantic.get("intent") if isinstance(semantic.get("intent"), str) else None
        acts = ([{"kind": intent, "confidence": float(semantic.get("confidence", .82)), "evidence": semantic.get("evidence", [])}] if intent else [])
        refs, context_trace = _context(text, history, list(conversation.get("context_refs") or []))
        slots = semantic.get("slots") if isinstance(semantic.get("slots"), dict) else {}
        target = slots.get("target") or slots.get("subject")
        subjects = ([{"text": target, "normalized": normalize(target).lower(), "source": "current", "confidence": .75}] if isinstance(target, str) and target else [])
        if refs:
            subjects = [{"text": ref["resolved_to"], "normalized": normalize(ref["resolved_to"]).lower(), "source": "context", "confidence": ref["confidence"]} for ref in refs if ref.get("resolved_to")] + subjects
        command = _command(text, semantic, dict(conversation.get("shell_risks") or {}))
        if command["present"]:
            acts.append({"kind": "command.action", "confidence": .91 if command["syntax"] == "shell_like" else .78, "evidence": command["evidence"]})
        if not acts:
            unknown.append(text)
            kind = "unknown.no_act" if _has_text(text) else "unknown.noise"
            acts = [{"kind": kind, "confidence": .40 if kind.endswith("no_act") else .72, "evidence": ["no_language_component_match"]}]
        acts.sort(key=lambda item: -item["confidence"])
        entities = [{"text": item, "kind": "url" if URL.fullmatch(item) else "path_or_file"} for item in dict.fromkeys(URL.findall(text) + PATH.findall(text))]
        modifiers = semantic.get("modifiers") if isinstance(semantic.get("modifiers"), dict) else {}
        constraints = list(modifiers.get("constraints") or [])
        if isinstance(slots.get("count"), str) and slots["count"]:
            constraints.append(slots["count"] + str(modifiers.get("count_unit") or ""))
        segment = {"raw": raw_segment, "normalized": text, "act_candidates": acts, "subject_candidates": subjects, "entities": entities, "modifiers": {"summary_target": modifiers.get("summary_target"), "format": list(modifiers.get("format") or []), "scope": list(modifiers.get("scope") or []), "constraints": list(dict.fromkeys(constraints)), "time": [], "negation": bool(modifiers.get("negation", False)), "question_form": bool(modifiers.get("question_form", False))}, "command": command, "context_refs": refs, "ambiguity": []}
        segment["goal"] = _goal(segment)
        segments.append(segment)
        traces.extend(context_trace + (["dialogue." + intent] if intent else ["dialogue.unmatched"]))
    primary = max((item for segment in segments for item in segment["act_candidates"]), key=lambda item: item["confidence"])
    needs = bool(unknown)
    return {"version": "2", "raw": raw, "normalized": normalized, "segments": segments, "overall": {"primary": primary, "confidence": primary["confidence"], "needs_clarification": needs, "unknown_parts": unknown}, "needs_clarification": needs, "unknown_parts": unknown, "trace": {"rule_ids": list(dict.fromkeys(traces)), "parser": getattr(parser, "component_id", type(parser).__name__), "language": pack["name"], "language_path": pack["path"]}}


def dialogue_reply(text: str, *, language: str | None = None, backend: DialogueBackend | None = None, language_pack: dict | None = None) -> str:
    pack = load_language_pack(language) if language_pack is None else language_pack
    candidate = resolve_backend(backend, pack).parse(normalize(text), pack) or {}
    replies = pack["conversation"].get("replies") or {}
    return replies.get(candidate.get("reply") or "fallback") or replies.get("fallback") or ""
