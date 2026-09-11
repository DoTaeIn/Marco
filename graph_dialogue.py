# -*- coding: utf-8 -*-
"""대화 말은 지식 그래프에 묻고, 요청 말끝은 활용으로 계산하는 해석 부품.

기본 ``TemplateBackend`` 는 적힌 꼴과 글자가 똑같아야 걸린다. 그래서
'안녕하세요' 는 알아듣고 '안녕' 은 못 알아들었다 — 두 낱말이 모두
``graphs/graph_대화예절.kg`` 의 ``*인사말`` 에 이미 적혀 있는데도 그랬다.
같은 지식이 언어팩과 지식팩에 두 번 적혀 있었고, 언어팩 쪽이 더 적었다.

여기서는 두 가지를 계산한다.

1. 대화 말은 그래프에 묻는다. 별칭도 답도 ``.kg`` 에 있으므로, 인사말을
   하나 늘리는 일이 그래프 한 줄이 된다. 언어팩은 안 고친다.
2. 요청 말끝은 ``활용`` 으로 만든다. '요약해줘' 와 '요약해 주세요' 와
   '요약해 줄래' 는 같은 어간에 다른 어미가 붙은 것이지, 서로 다른 틀이
   아니다. 어미를 하나 더 선언하면 모든 동작이 그 꼴을 함께 얻는다.
"""
from __future__ import annotations

import re
from typing import Any

import hangul


def _squeeze(text: str) -> str:
    return "".join(text.split())


class GraphDialogueBackend:
    """``language_components.DialogueBackend`` 를 그래프와 문법으로 구현한다."""

    component_id = "graph-dialogue-v1"

    def __init__(self, graph_path: str = "graphs/graph_대화예절.kg", *,
                 loader=None, judge=None, router=None):
        self.graph_path = graph_path
        self._loader, self._judge, self._router = loader, judge, router
        self._graph = None
        self._graph_failed = False
        self._tails: dict[str, frozenset[str]] = {}

    # --- 대화 말 -------------------------------------------------------
    def _engine(self):
        if self._loader is not None and self._judge is not None:
            return self._loader, self._judge
        import engine
        return engine.load, engine.judge

    def _routes_here(self, text: str) -> bool:
        """라우터도 이 그래프를 골랐을 때만 대화로 본다.

        한 그래프에만 물으면 그 그래프가 아는 짧은 말이 긴 문장 안에 묻혀
        있어도 걸린다 — 'DNS는 사람이 읽는 이름을 ... 연결해 준다' 가
        인사 그래프에 붙었다(고정 물음 800개 중 31개). 라우터는 905개를
        견주므로, 그 견줌을 다시 하지 않고 결과에 따른다.

        라우터가 없으면 대화로 보지 않는다. 확인 못 한 것을 인정하지
        않는다는 규율이 여기에도 그대로 적용된다.
        """
        router = self._router
        if router is None:
            try:
                import engine
                router = engine.pick_graph
            except Exception:
                return False
        try:
            name, _score, _cand = router(text)
        except Exception:
            return False
        return bool(name) and str(name).endswith(self.graph_path.rsplit("/", 1)[-1])

    def _etiquette(self):
        if self._graph is None and not self._graph_failed:
            try:
                load, _ = self._engine()
                self._graph = load(self.graph_path)
            except Exception:
                # 그래프를 못 읽으면 대화 갈래만 포기한다. 요청 해석은 계속한다.
                self._graph_failed = True
        return self._graph

    def _dialogue(self, text: str) -> dict[str, Any] | None:
        if not self._routes_here(text):
            return None
        graph = self._etiquette()
        if graph is None:
            return None
        _, judge = self._engine()
        try:
            verdict, sentence = judge(graph, text)
        except Exception:
            return None
        # 그래프가 제 임계값으로 인정한 것만 대화로 본다. 여기에 길이나
        # 점수 문턱을 따로 두지 않는다 — 그 판단은 .kg 의 임계값 몫이다.
        if verdict != "인정" or not sentence:
            return None
        return {"intent": "dialogue", "reply": "graph", "reply_text": sentence,
                "confidence": 0.82, "evidence": [self.graph_path]}

    # --- 요청 말 -------------------------------------------------------
    def _tail_set(self, pack: dict[str, Any]) -> frozenset[str]:
        """<동작> 뒤에 붙을 수 있는 꼬리를 어간과 어미에서 만든다.

        꼬리는 세 자리로 이루어진다 — 군말('좀'·'부탁해'), 본용언의 활용
        ('해'·'하세요'), 보조용언의 활용('줘'·'주세요'·'줄래'). 세 자리를
        각각 비울 수 있게 곱하므로, 어미를 하나 선언하면 모든 동작이 그
        꼴을 함께 얻는다. 꼴을 하나씩 적어 두지 않는다.
        """
        request = pack.get("conversation", {}).get("request") or {}
        grammar = pack.get("inflection") or {}
        key = str(grammar.get("id")) + "|" + repr(request)
        cached = self._tails.get(key)
        if cached is not None:
            return cached
        light = [""] + _all_forms(request.get("light_verb"), request.get("light_endings"), grammar)
        helper = [""] + _all_forms(request.get("auxiliary"), request.get("auxiliary_endings"), grammar)
        bare = [""] + [_squeeze(m) for m in (request.get("bare_markers") or []) if isinstance(m, str)]
        tails = {marker + stem + tail for marker in bare for stem in light for tail in helper}
        tails.update(stem + marker for marker in bare for stem in light)
        value = frozenset(tails)
        self._tails[key] = value
        return value

    def _request(self, text: str, pack: dict[str, Any]) -> dict[str, Any] | None:
        request = pack.get("conversation", {}).get("request") or {}
        actions = [a for a in (request.get("actions") or []) if isinstance(a, dict)]
        if not actions:
            return None
        squeezed = _squeeze(text).rstrip("?!.~")
        tails = self._tail_set(pack)
        best = None
        for action in actions:
            stem = str(action.get("stem") or "")
            intent = action.get("intent")
            if not stem or not isinstance(intent, str):
                continue
            start = squeezed.rfind(stem)
            if start < 0:
                continue
            tail = squeezed[start + len(stem):]
            if tail not in tails:
                continue
            target = _target(text, stem)
            candidate = dict(action.get("result") or {})
            candidate.update({"intent": intent, "confidence": 0.82,
                              "evidence": [stem + tail if tail else stem]})
            slots = dict(candidate.get("slots") or {})
            modifiers = dict(candidate.get("modifiers") or {})
            count, unit, formats, rest = _measure(target, request, pack)
            if count is not None:
                slots["count"], modifiers["count_unit"] = str(count), unit
            if formats:
                modifiers["format"] = list(dict.fromkeys(list(modifiers.get("format") or []) + formats))
            if rest:
                slots["target"] = rest
            candidate["slots"], candidate["modifiers"] = slots, modifiers
            # 긴 어간이 이긴다. '요약' 과 '약' 이 함께 선언돼도 흔들리지 않는다.
            if best is None or len(stem) > best[0]:
                best = (len(stem), candidate)
        return best[1] if best else None

    # --- 계약 ----------------------------------------------------------
    def parse(self, text: str, pack: dict[str, Any]) -> dict[str, Any] | None:
        """요청이 먼저다. '다시 설명해 주세요' 는 되묻기가 아니라 요청이다."""
        return self._request(text, pack) or self._dialogue(text)


def _all_forms(stem, endings, grammar: dict[str, Any]) -> list[str]:
    """선언된 어미로 만들 수 있는 꼴만 모은다. 없는 활용은 지어내지 않는다."""
    if not isinstance(stem, str) or not stem or not grammar:
        return []
    out = []
    for ending in endings or []:
        if not isinstance(ending, str):
            continue
        try:
            forms = hangul.inflect(stem, "present", ending, grammar, kind="regular")
        except Exception:
            continue
        out.extend(form["text"] for form in forms)
    return list(dict.fromkeys(out))


def _target(text: str, stem: str) -> str:
    head = text.rsplit(stem, 1)[0].strip() if stem in text else ""
    return head.strip(" ,:;-")


def _measure(target: str, request: dict[str, Any], pack: dict[str, Any]):
    """대상말에서 셈과 꼴을 떼어 낸다.

    '3줄'의 3도 '세 줄'의 세도 같은 셈이다. 아라비아 숫자만 알아보면
    사람이 쓰는 절반을 놓친다 — 수사는 언어팩의 ``numerals`` 로 읽는다.

    낱말 자리는 ``hangul.word_spans`` 가 가린다. '발표자료'의 '표'를 꼴말로
    읽으면 안 되고, '3줄로'의 '줄'은 조사가 붙어도 세는말이다. 그 구분은
    한 군데(한글 문법)에만 있어야 하므로 여기서 다시 만들지 않는다.
    """
    units = [u for u in (request.get("count_units") or []) if isinstance(u, str) and u]
    table = request.get("formats") or {}
    numerals = (pack.get("relations") or {}).get("numerals") or {}
    count = unit = None
    rest = target
    for name in units:
        for start, end in hangul.word_spans(rest, name):
            head = rest[:start].rstrip()
            word = re.search(r"([0-9]+|[가-힣]+)$", head)
            if not word:
                continue
            value = int(word.group(1)) if word.group(1).isdigit() else _numeral(word.group(1), numerals)
            if value is None:
                continue
            count, unit = value, name
            # 세는말을 떼면 그 뒤 조사가 홀로 남는다 — '세 줄로' 를 떼고
            # '로' 만 남기면 대상말이 '회의록 로' 가 된다.
            rest = rest[:word.start(1)] + hangul.strip_particle(rest[end:])
            break
        if count is not None:
            break
    # 꼴말은 도구격('표로'·'불릿으로')일 때만 꼴이다. '이 표 설명해 주세요'
    # 의 '표'는 꼴이 아니라 설명할 대상이다. 어느 꼴로 붙는지는 받침이
    # 정하므로 한글 문법에 묻는다.
    formats, taken = [], []
    for word, name in table.items():
        if not isinstance(word, str) or not word:
            continue
        particle = hangul.pick_particle(word, "으로/로")
        spans = [(s, e) for s, e in hangul.word_spans(rest, word)
                 if rest[e:e + len(particle)] == particle]
        if not spans:
            continue
        formats.append(str(name))
        taken.extend((s, e + len(particle)) for s, e in spans)
    for start, end in sorted(taken, reverse=True):
        rest = rest[:start] + " " + rest[end:]
    return count, unit, formats, " ".join(rest.split()).strip(" ,:;-")


def _hangul(char: str) -> bool:
    return bool(char) and "\uac00" <= char <= "\ud7a3"


def _numeral(word: str, numerals: dict[str, Any]):
    if not numerals:
        return None
    try:
        from numeral_semantics import parse_numeral
        return parse_numeral(word, numerals)
    except Exception:
        return None


def backend() -> GraphDialogueBackend:
    return GraphDialogueBackend()
