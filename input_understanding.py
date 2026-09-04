# -*- coding: utf-8 -*-
"""로컬 규칙만으로 사용자 입력을 구조화한다.

이 모듈은 답변, 검색, 그래프 라우팅, 파일·네트워크 작업을 하지 않는다.
``understand``의 반환값은 UI/API에 그대로 내보낼 수 있는 JSON 자료형이다.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parent
DEFAULT_RULES = {
    "intent": {
        "summary": ["요약", "summarize", "tl;dr"],
        "explain": ["설명", "알려줘", "가르쳐", "explain", "what is", "how does"],
        "compare": ["비교", "차이", "compare", "versus", "vs"],
        "extract": ["추출", "뽑아", "찾아줘", "extract", "list"],
        "rewrite": ["다시 써", "재작성", "고쳐", "rewrite", "translate"],
        "plan": ["계획", "플랜", "plan"],
        "create": ["만들어", "생성", "작성", "create", "write"],
    },
    "question_markers": ["?", "왜", "어떻게", "무엇", "뭐", "언제", "어디", "누가", "얼마", "인가", "인가요", "나요", "까", "해?"],
    "context_refs": ["그거", "그것", "이거", "이것", "저거", "아까", "위에", "앞의", "방금", "거기", "앞에서"],
    "command": {
        "read": ["보여", "읽어", "열어", "확인", "조회", "cat ", "ls", "git status"],
        "write": ["저장", "수정", "바꿔", "작성", "만들어", "생성", "복사", "mkdir", "touch", "cp ", "mv "],
        "destructive": ["지워", "삭제", "제거", "rm ", "drop ", "truncate", "reset --hard", "format"],
        "external": ["보내", "업로드", "배포", "게시", "메일", "공유", "push ", "curl ", "wget "],
        "credential_or_unknown": ["비밀번호", "password", "token", "api key", "secret", "sudo", "ssh "],
    },
    "dialogue_reply": {
        "greeting": "안녕하세요. 궁금한 점이나 하려는 작업을 말씀해 주세요.",
        "thanks": "천만에요. 이어서 필요한 것을 말씀해 주세요.",
        "fallback": "말씀을 이해했습니다. 질문이나 목표를 조금 더 구체적으로 알려 주세요.",
    },
}
SHELL_HEAD = re.compile(r"^\s*(?:[$#]\s*)?(?:rm|mv|cp|cat|ls|find|grep|sed|awk|git|curl|wget|ssh|chmod|mkdir|touch|python(?:3)?|node|npm|pip|docker|kubectl|sql)\b", re.I)
URL = re.compile(r"https?://[^\s<>]+", re.I)
PATH = re.compile(r"(?:\.?\.?/|/)[\w.\-~/]+|\b[\w.-]+\.(?:py|js|ts|json|md|txt|csv|html|css|kg|kgpack)(?=$|[\s,;:)\]}>\"']|[이가을를은는에의로])", re.I)


def _rules():
    try:
        style = json.loads((ROOT / "styles" / "한국어.json").read_text(encoding="utf-8"))
        custom = style.get("입력이해") or {}
    except (OSError, json.JSONDecodeError):
        custom = {}
    rules = json.loads(json.dumps(DEFAULT_RULES))
    for key, value in custom.items():
        if isinstance(value, dict) and isinstance(rules.get(key), dict):
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, list) and isinstance(rules[key].get(nested_key), list):
                    rules[key][nested_key] = list(dict.fromkeys(rules[key][nested_key] + nested_value))
                else:
                    rules[key][nested_key] = nested_value
        elif value:
            rules[key] = value
    return rules


def normalize(text):
    """원문을 보존한 채 비교용 공백·유니코드만 정리한다."""
    text = unicodedata.normalize("NFC", str(text or "")).replace("\u200b", "")
    return re.sub(r"[ \t\f\v]+", " ", text).strip()


def _protected_ranges(text):
    ranges = []
    for match in re.finditer(r"```.*?```|`[^`\n]+`|https?://[^\s<>]+", text, re.S | re.I):
        ranges.append((match.start(), match.end()))
    return ranges


def _inside(index, ranges):
    return any(start <= index < end for start, end in ranges)


def split_segments(text):
    """인용·코드·URL 안의 기호를 건드리지 않고 요청 대목을 나눈다."""
    ranges = _protected_ranges(text)
    cut_at, start = [], 0
    for index, char in enumerate(text):
        if _inside(index, ranges):
            continue
        if char in "\n;" or (char in ".!?。！？" and (index + 1 == len(text) or text[index + 1].isspace())):
            if text[start:index].strip():
                cut_at.append((start, index + 1))
            start = index + 1
    if text[start:].strip():
        cut_at.append((start, len(text)))
    parts = [text[a:b].strip(" \t\r\n,;:") for a, b in cut_at]
    return [part for part in parts if part] or ([text] if text else [])


def _matches(text, phrases):
    lowered = text.lower()
    return [phrase for phrase in phrases if phrase and phrase.lower() in lowered]


def _candidates(text, rules):
    candidates, trace = [], []
    for kind, phrases in rules["intent"].items():
        hits = _matches(text, phrases)
        if hits:
            candidates.append({"kind": "request." + kind, "confidence": min(.96, .60 + .11 * len(hits)), "evidence": hits})
            trace.append("intent." + kind)
    question = _matches(text, rules["question_markers"])
    if question:
        candidates.append({"kind": "question", "confidence": .76 if "?" in question else .62, "evidence": question})
        trace.append("question.marker")
    if not candidates and re.search(r"^(?:안녕|고마워|감사|반가워|ㅎㅎ|ㅋㅋ|hi|hello)\b", text, re.I):
        candidates.append({"kind": "dialogue", "confidence": .82, "evidence": ["greeting"]})
        trace.append("dialogue.greeting")
    return candidates, trace


def _command(text, rules):
    hits = {risk: _matches(text, phrases) for risk, phrases in rules["command"].items()}
    shell = bool(SHELL_HEAD.search(text))
    present = shell or any(hits.values())
    if not present:
        return {"present": False, "syntax": None, "risk": "none", "evidence": [], "execution_allowed": False}, []
    priority = ("credential_or_unknown", "destructive", "external", "write", "read")
    risk = next((name for name in priority if hits[name]), "credential_or_unknown" if shell else "unknown")
    evidence = [item for values in hits.values() for item in values]
    if shell:
        evidence.append("shell-like")
    return {"present": True, "syntax": "shell_like" if shell else "natural_language", "risk": risk,
            "evidence": list(dict.fromkeys(evidence)), "execution_allowed": False}, ["command." + risk]


def _goal(segment):
    """답변과 실행을 같은 상위 흐름에서 고를 수 있는 목적 요약이다."""
    command = segment["command"]
    acts = [item["kind"] for item in segment["act_candidates"]]
    subject = next((item for item in segment["subject_candidates"] if item["source"] in ("context", "current")), None)
    if command["present"]:
        kind = "perform"
    elif any(item.startswith("request.") for item in acts):
        kind = "inform"
    elif "question" in acts:
        kind = "answer"
    else:
        kind = "clarify"
    return {"kind": kind, "subject": subject["text"] if subject else None,
            "requested_actions": acts, "risk": command["risk"],
            "output": ("action_result" if kind == "perform" else "grounded_answer")}


def _modifiers(text):
    lines = re.search(r"(?:^|\s)(\d{1,3})\s*(?:줄|문장|개|가지)(?:로|으로|의|씩)?(?![가-힣A-Za-z0-9])", text)
    formats = []
    for name, pattern in (("bullets", r"(?:불릿|목록|리스트|bullet)"), ("table", r"(?:표로|테이블|table)"),
                          ("short", r"(?:짧게|간단히|brief)"), ("detailed", r"(?:자세히|상세히|detailed)")):
        if re.search(pattern, text, re.I):
            formats.append(name)
    negation = bool(re.search(r"(?:하지 ?마|말고|않[아습]|없이|제외)", text))
    scope = re.findall(r"(?:전체|전부|이 부분|이 문서|이 파일|앞의|위의)\s*[가-힣A-Za-z0-9_.\-/]*", text)
    return {"summary_target": "summary" if re.search(r"요약|summarize|tl;dr", text, re.I) else None,
            "format": formats, "scope": scope, "constraints": (["%s줄" % lines.group(1)] if lines else []),
            "time": [], "negation": negation,
            "question_form": bool(re.search(r"[?？]", text) or re.search(r"(?:왜|어떻게|무엇|뭐|언제|어디|누가|인가|나요|까)\b", text))}


def _subjects(text, rules, context_refs):
    cleaned = text
    for phrase in [p for values in rules["intent"].values() for p in values] + rules["question_markers"] + rules["context_refs"]:
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?:좀|제발|해줘|주세요|해라|해봐|를|을|은|는|이|가|에|의|로|으로)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?:;\n")
    candidates = []
    if cleaned and len(cleaned) >= 2 and re.search(r"[가-힣A-Za-z0-9]{2,}", cleaned):
        candidates.append({"text": cleaned[:180], "normalized": normalize(cleaned).lower(), "source": "current", "confidence": .66})
    entities = []
    for token in list(dict.fromkeys(URL.findall(text) + PATH.findall(text))):
        entities.append({"text": token, "kind": "url" if URL.fullmatch(token) else "path_or_file"})
    return candidates, entities


def _context(text, history, rules):
    refs = _matches(text, rules["context_refs"])
    if not refs:
        return [], []
    candidates = []
    for age, item in enumerate(reversed(history[-12:]), 1):
        for segment in item.get("segments", []):
            for subject in segment.get("subject_candidates", []):
                if subject.get("source") == "current" and subject.get("text"):
                    candidates.append({"text": subject["text"], "turns_ago": age,
                                       "confidence": round(max(.35, .84 - .06 * (age - 1)), 2)})
    unique = []
    for candidate in candidates:
        if candidate["text"] not in {x["text"] for x in unique}:
            unique.append(candidate)
    if not unique:
        return [{"text": ref, "resolved_to": None, "confidence": 0, "reason": "session_has_no_prior_subject"} for ref in refs], ["context.no_history"]
    best = unique[:3]
    return [{"text": ref, "resolved_to": best[0]["text"], "confidence": best[0]["confidence"],
             "alternatives": best[1:], "reason": "recent_session_subject"} for ref in refs], ["context.session"]


def understand(raw, history=None):
    """입력을 분석한다. history는 같은 브라우저 세션의 과거 결과만 허용한다."""
    history = list(history or [])
    raw = str(raw or "")
    normalized = normalize(raw)
    if not normalized:
        raise ValueError("입력이 비어 있습니다")
    rules = _rules()
    segments, all_trace, unknown = [], [], []
    for raw_segment in split_segments(raw):
        text = normalize(raw_segment)
        act_candidates, trace = _candidates(text, rules)
        command, command_trace = _command(text, rules)
        if command["present"]:
            act_candidates.append({"kind": "command.action", "confidence": .91 if command["syntax"] == "shell_like" else .68,
                                   "evidence": command["evidence"]})
        refs, context_trace = _context(text, history, rules)
        subjects, entities = _subjects(text, rules, refs)
        if refs:
            resolved = []
            for ref in refs:
                if ref["resolved_to"]:
                    resolved.append({"text": ref["resolved_to"], "normalized": normalize(ref["resolved_to"]).lower(),
                                     "source": "context", "confidence": ref["confidence"]})
            # 지시어가 있을 때는 최근 문맥 후보를 먼저 보인다. 현재 문장에 남은 형식어는
            # 보조 후보로 유지해, 해석을 단정하지 않는다.
            subjects = resolved + subjects
        # 후보가 비면 아래 max() 가 터진다. 실제로 '저녁 메뉴 추천해줘' 가
        # 그렇게 죽었다 — 규칙에 없는 '추천' 뿐이라 행동은 안 걸리는데,
        # '저녁 메뉴' 가 주제로 잡혀 opaque 가 False 였다.
        #
        # 둘을 갈라 적는다. 무엇에 대한 말인지도 모르는 것과, 무엇에 대한
        # 말인지는 알지만 뭘 하라는지 모르는 것은 다른 상태다. 뭉쳐서
        # '잡음' 이라 하면 사람이 멀쩡히 한 말을 딴소리로 단정하게 된다.
        if not act_candidates:
            unknown.append(text)
            if not subjects and not entities:
                act_candidates.append({"kind": "unknown.noise", "confidence": .72,
                                       "evidence": ["no_deterministic_signal"]})
                trace.append("unknown.no_signal")
            else:
                # 주제는 잡혔다. 행동만 모르므로 확신을 낮게 두고 되묻게 한다.
                act_candidates.append({"kind": "unknown.no_act", "confidence": .40,
                                       "evidence": ["subject_without_known_act"]})
                trace.append("unknown.no_act")
        act_candidates.sort(key=lambda item: -item["confidence"])
        ambiguity = []
        if len(act_candidates) > 1:
            ambiguity.append({"kind": "multiple_intents", "alternatives": [x["kind"] for x in act_candidates[:3]], "reason": "several_local_rules_matched"})
        if refs and refs[0].get("alternatives"):
            ambiguity.append({"kind": "context_reference", "alternatives": [x["text"] for x in refs[0]["alternatives"]], "reason": "multiple_session_subjects"})
        segment = {"raw": raw_segment, "normalized": text, "act_candidates": act_candidates,
                         "subject_candidates": subjects, "entities": entities, "modifiers": _modifiers(text),
                         "command": command, "context_refs": refs, "ambiguity": ambiguity}
        segment["goal"] = _goal(segment)
        segments.append(segment)
        all_trace.extend(trace + command_trace + context_trace)
    # default 를 둔다. 위에서 세그먼트마다 후보를 채우므로 여기까지 비어서
    # 오는 길은 이제 없지만, 이 한 줄이 터지면 UI 가 통째로 오류만 뱉는다.
    # 분석기가 못 알아듣는 것과 죽는 것은 다르다.
    primary = max((x for segment in segments for x in segment["act_candidates"]),
                  key=lambda item: item["confidence"],
                  default={"kind": "unknown.noise", "confidence": .0,
                           "evidence": ["no_segment_candidate"]})
    return {"version": "1", "raw": raw, "normalized": normalized, "segments": segments,
            "overall": {"primary": primary, "confidence": primary["confidence"],
                        "needs_clarification": bool(unknown) or any(s["ambiguity"] for s in segments),
                        "unknown_parts": unknown},
            "needs_clarification": bool(unknown) or any(s["ambiguity"] for s in segments),
            "unknown_parts": unknown, "trace": {"rule_ids": list(dict.fromkeys(all_trace)), "parser": "local_deterministic_v1"}}


def dialogue_reply(text):
    """지식/검색으로 보내면 부자연스러운 간단한 대화에만 쓴다."""
    reply = _rules().get("dialogue_reply") or DEFAULT_RULES["dialogue_reply"]
    normalized = normalize(text).lower()
    if any(word in normalized for word in ("고마", "감사", "thanks", "thank you")):
        return reply.get("thanks") or DEFAULT_RULES["dialogue_reply"]["thanks"]
    if re.search(r"^(?:안녕|반가|hi|hello)\b", normalized, re.I):
        return reply.get("greeting") or DEFAULT_RULES["dialogue_reply"]["greeting"]
    return reply.get("fallback") or DEFAULT_RULES["dialogue_reply"]["fallback"]


if __name__ == "__main__":
    import unittest

    class InputUnderstandingTest(unittest.TestCase):
        def test_summary_context_and_command_are_not_actions(self):
            first = understand("소고기뭇국 레시피를 자세히 설명해줘")
            result = understand("그거 3줄로 요약해줘", [first])
            self.assertEqual(result["segments"][0]["subject_candidates"][0]["source"], "context")
            self.assertIn("3줄", result["segments"][0]["modifiers"]["constraints"])
            command = understand("rm -rf ./tmp")
            self.assertEqual(command["segments"][0]["command"]["risk"], "destructive")
            self.assertFalse(command["segments"][0]["command"]["execution_allowed"])

    unittest.main()
