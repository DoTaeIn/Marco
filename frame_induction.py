# -*- coding: utf-8 -*-
"""뜻풀이의 틀을 손으로 적지 않고 이미 있는 사례에서 꺼낸다.

뜻풀이의 몸통은 **보통 문장**이다. 다만 사건이 채울 자리가 비어 있을 뿐이다.

    치우다는 [     ] 물건을 상자로 옮기는 것이다
    하루가       연필을        치웠다

그래서 몸통은 **앞자리를 지운 사례**에 맞춰 읽고, 비어 있던 자리는 사건이
**같은 조사로** 채운다. 짜임이 하나 늘 때마다 틀을 새로 선언하지 않는다.

여기서 선언에 기대는 것은 둘뿐이고, 둘 다 낱말마다 늘지 않는다.

* 조사 — 닫힌 낱말갈래다. 한국어의 조사는 세다가 끝난다.
* 이미 적혀 있는 보통 문장 사례 — 틀이 아니라 문장이다.

그래서 못 읽는 뜻풀이가 남는다면 그것은 **틀이 없어서가 아니라 몸통의 동사를
모르기 때문**이다. 이 둘은 값이 다르다. 틀은 끝없이 늘고 동사는 유한하다.
"""
from copy import deepcopy

from hangul import inflect
from relational_semantics import asserted, substitute


def particle_key(particle, groups):
    """같은 자리를 채우는 조사는 한 이름으로 부른다. `로` 와 `으로` 는 한 자리다."""
    for group in groups:
        if particle in group:
            return group[0]
    return particle


def split_particle(word, particles, groups):
    """낱말을 (앞말, 자리) 로 가른다. 조사가 안 보이면 None."""
    for particle in particles:                      # 긴 조사를 먼저 본다
        if len(word) > len(particle) and word.endswith(particle):
            return word[:-len(particle)], particle_key(particle, groups)
    return None


def _marked(value, particles, groups):
    """이 값이 **조사를 넘어서 잘렸나.** 넘어섰으면 자름이 틀렸다.

    낱말 하나만 잡았다면 조사를 넘은 것이 아니다. 낱말 하나에 대고 조사를 떼
    보면 멀쩡한 이름을 버린다 — `사과` 의 `과`, `모과` 의 `과` 는 조사가 아니라
    이름의 끝 글자다. 조사는 앞말에 붙고 뒤는 띄우므로, **띄어쓰기를 넘어선
    자리에 조사가 보일 때만** 잘못 잘린 것이다.
    """
    words = value.split()
    return len(words) > 1 and any(split_particle(word, particles, groups) for word in words)


def _spans(example):
    text, slots = example["text"], example["slots"]
    return sorted((text.index(v), text.index(v) + len(v), k) for k, v in slots.items())


def _particle_at(text, end, particles, groups):
    """이 자리 바로 뒤에 붙은 조사. 조사가 아니면 None."""
    rest = text[end:]
    for particle in particles:
        if rest.startswith(particle) and not rest[len(particle):len(particle) + 1].strip():
            return particle_key(particle, groups)
    return None


def _chunks(example, particles, groups):
    """예문을 **조사가 끝맺는 덩이**로 나눈다. 덩이마다 그 안의 자리도 함께.

        하루가 | 모래에게 | 구슬 2개를 | 줬다
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^ 풀이말

    덩이를 알면 자리를 빼는 것도 자리 순서를 바꾸는 것도 같은 일이 된다.
    한국어는 조사가 자리를 짚으므로 덩이 순서는 뜻을 안 바꾼다.
    """
    text, spans = example["text"], _spans(example)
    tokens, cursor = [], 0
    for word in text.split():
        start = text.index(word, cursor)
        tokens.append((start, start + len(word)))
        cursor = start + len(word)
    chunks, current = [], []
    for start, end in tokens:
        current.append((start, end))
        if split_particle(text[start:end], particles, groups):
            chunks.append(current); current = []
    def inside(piece):
        low, high = piece[0][0], piece[-1][1]
        return {name: example["slots"][name] for s, e, name in spans if low <= s and e <= high}
    return ([(text[piece[0][0]:piece[-1][1]], inside(piece)) for piece in chunks],
            (text[current[0][0]:] if current else ""),
            (inside(current) if current else {}))


def _elisions(example, particles, groups, reorder=False):
    """자리를 빼고 순서를 바꾼 조각 사례들. 뺀 자리가 곧 사건이 채울 자리다.

    앞에서부터만 빼면 `구슬 2개를 상대에게 주는` 처럼 **순서만 다른** 말을 못
    읽는다. 반례마다 예문을 더하지 않고 덩이를 다시 늘어놓는다.
    """
    from itertools import combinations, permutations
    text = example["text"]
    chunks, tail, tail_slots = _chunks(example, particles, groups)
    if not chunks:
        return
    seen = set()
    for keep in range(len(chunks), -1, -1):
        arrangements = (permutations(range(len(chunks)), keep) if reorder else
                        combinations(range(len(chunks)), keep))
        for chosen in arrangements:
            order = sorted(chosen)
            dropped = {}
            for index, (_piece, slots) in enumerate(chunks):
                if index in chosen:
                    continue
                for name in slots:
                    end = text.index(example["slots"][name]) + len(example["slots"][name])
                    dropped[name] = _particle_at(text, end, particles, groups)
            if any(key is None for key in dropped.values()):
                continue            # 조사 없이 지워진 자리는 사건이 채울 길이 없다
            body = " ".join(chunks[index][0] for index in chosen)
            piece_text = " ".join(part for part in (body, tail) if part)
            if piece_text in seen or not piece_text:
                continue
            seen.add(piece_text)
            kept = dict(tail_slots)
            for index in chosen:
                kept.update(chunks[index][1])
            if any(piece_text.count(value) != 1 for value in kept.values()):
                continue            # 순서를 바꾸다 같은 글자가 둘이 되면 못 가른다
            piece = {k: v for k, v in example.items() if k != "inflection"}
            piece["text"], piece["slots"] = piece_text, kept
            yield piece, dropped, len(chunks) - keep, list(chosen) != order


def _finite(body, example, grammar):
    """몸통의 꼬리를 그 사례가 쓰는 마침꼴로 되돌린다. **아는 어간만** 본다.

    매김꼴(`주는`)만 되돌리면 이어지는 말(`주고`)을 못 읽는다. 꼬리마다 따로
    적지 않는다 — 언어팩이 그 어간의 꼴을 이미 다 계산하므로, 그 가운데 몸통의
    끝과 맞는 것을 찾아 그 사례가 쓰는 꼴로 바꿔 놓을 뿐이다.
    """
    yield body
    annotation = example.get("inflection")
    if not annotation or not grammar:
        return
    try:
        canonical = [form["text"] for form in
                     inflect(annotation["stem"], annotation["tense"], annotation["ending"],
                             grammar, kind=annotation["kind"])]
    except ValueError:
        return
    꼴 = set()
    for tense in grammar.get("tenses", {}):
        for ending in grammar.get("endings", {}):
            try:
                꼴 |= {form["text"] for form in
                      inflect(annotation["stem"], tense, ending, grammar,
                              kind=annotation["kind"])}
            except ValueError:
                continue
    for form in sorted(꼴, key=len, reverse=True):
        if body.endswith(form) and len(body) > len(form):
            for tail in canonical:
                yield body[:-len(form)] + tail


def _rename(value, prefix):
    """절마다 자리 이름이 겹치지 않게 앞에 표를 붙인다."""
    if isinstance(value, str):
        return "$" + prefix + value[1:] if value.startswith("$") else value
    if isinstance(value, list):
        return [_rename(item, prefix) for item in value]
    if isinstance(value, dict):
        # ``into`` declares a produced variable rather than referring to one
        # with a `$` prefix.  Clause composition must namespace it too, or a
        # later `$c0_basis` reference points at a value that was never bound.
        return {key: (prefix + item if key == "into" and isinstance(item, str)
                      else _rename(item, prefix))
                for key, item in value.items()}
    return value


def _clauses(body, grammar):
    """몸통을 절로 나눈다. 이음꼴로 끝나는 앞절과 나머지.

        내가 상대에게 구슬 두 개를 주고, 상대가 나에게 단추 한 개를 주는
        └────────── 앞절(`-고`) ──────────┘  └──────── 뒷절 ────────┘

    이음꼴 목록은 언어팩이 이미 적어 둔 것을 쓴다. 맞교환 전용 규칙이 아니다.
    """
    pieces = [piece.strip() for piece in body.split(",")]
    if len(pieces) < 2 or not all(pieces):
        return []
    꼬리들 = grammar.get("candidate_suffixes", [])
    if not all(any(piece.endswith(꼬리) for 꼬리 in 꼬리들) for piece in pieces[:-1]):
        return []
    return pieces


def _from_rule(parser, clause, 배운것):
    """절이 **이 대화에서 배운 동작**이면 그 뜻틀을 그대로 가져다 쓴다.

    문장을 새로 지어 다시 읽지 않는다. 이미 만들어 둔 동작·역할 얼개에 이 절의
    낱말을 앉힐 뿐이다 — 그래서 원문도, 그 동작이 어느 시점의 뜻이었는지도
    그대로 남는다. 동사마다 따로 처리하는 곳은 없다.
    """
    뜻표 = (배운것 or {}).get("뜻") or {}
    꼴표 = (배운것 or {}).get("꼴") or {}
    words = clause.strip().rstrip(".!?…").split()
    if not 뜻표 or len(words) < 2:
        return None
    stem = 꼴표.get(words[-1])
    쓸것 = 뜻표.get(stem)
    if 쓸것 is None:
        return None
    후보, _잘림 = _chunkings(words[:-1], parser.case_particles, parser.slot_particles)
    if not 후보:
        return None
    자리 = {particle_key(key, parser.slot_particles): value
           for key, value in 후보[0].items()}
    값, 앉힘 = dict(쓸것["값"]), {}
    for name, key in {**쓸것["빈자리"], **쓸것["채울자리"]}.items():
        if key not in 자리:
            return None            # 이 절이 그 자리를 안 짚었다
        값[name], 앉힘[name] = 자리[key], key
    # 배운 동작을 부를 때도 **절이 짚은 나머지 자리**를 봐야 한다. 안 보면
    # `내가 물건을 학교로 치우고` 의 `학교로` 가 조용히 버려지고 뜻풀이가 정해 둔
    # `상자` 가 쓰인다. 뜻풀이가 정한 값과 어긋나거나 뜻풀이에 없는 자리가 남으면
    # 우리가 고르지 않는다 — 못 읽은 것으로 드러낸다.
    for key, value in 자리.items():
        if key in 앉힘.values():
            continue
        name = next((n for n, k in 쓸것["자리"].items() if k == key), None)
        if name is None or 쓸것["값"].get(name) != value:
            return None
    자리표 = {**쓸것["자리"], **앉힘}
    # Keep both the expanded meaning (for compatibility and inspection) and
    # an executable call edge.  The runtime gets the latter, so a composed
    # natural definition reuses the referenced action's binding/execution
    # contract instead of reimplementing its effect in the outer action.
    reference_version = (배운것 or {}).get("때", {}).get(stem)
    return {"뜻": 쓸것["뜻"], "값": 값, "자리": 자리표, "빈자리": {},
            "채울자리": _open(값, 자리표, parser.placeholders),
            "호출": [{"action": stem, "definition_version": reference_version,
                     "role_slots": dict(자리표), "values": dict(값)}],
            "프로그램단계": [{"op": "call", "action": stem,
                              "definition_version": reference_version,
                              "roles": {slot: "$" + name
                                        for name, slot in 자리표.items()}}],
            "삼킴": sum(_marked(value, parser.case_particles, parser.slot_particles)
                      for value in 앉힘 and [값[name] for name in 앉힘]),
            "쓴동사": sorted({stem} | set(쓸것.get("쓴동사") or ()))}


def _compose(parser, body, 배운것=None):
    """절이 여럿인 몸통. **절마다 따로 읽고 자리말로 잇는다.**

    이미 아는 동작을 엮을 뿐이고 새 연산을 만들지 않는다. 두 절에 같은 자리말이
    나오면 **같은 것을 가리킨다** — 그래서 뒷절에서 주는이와 받는이가 뒤집히는
    일이 따로 적지 않아도 나온다. 자리말이 처음 나온 절의 조사가 그 자리의
    조사가 된다.
    """
    pieces = _clauses(body, parser.clause_grammar)
    if not pieces:
        return None
    읽은절, 역할조사 = [], {}
    for piece in pieces:
        읽음 = induce(parser, piece, 배운것)
        if 읽음 is None:
            return None
        읽은절.append(읽음)
    # **그 일을 한 쪽은 임자 자리에 선다.** 절에 먼저 나온 순서로 정하면
    # 방향을 뒤집어 적은 뜻풀이가 같은 결과를 낸다.
    말하는이 = parser.placeholders.get(parser.speaker_placeholder)
    if 말하는이 is not None:
        역할조사[말하는이] = particle_key(parser.doer_particle, parser.slot_particles)
    쓴조사 = set(역할조사.values())
    for 읽음 in 읽은절:
        for name, key in 읽음["채울자리"].items():
            역할 = parser.placeholders.get(읽음["값"].get(name))
            if 역할 is None or 역할 in 역할조사 or key in 쓴조사:
                continue
            역할조사[역할] = key
            쓴조사.add(key)
    # 자리말이 둘인데 조사가 하나면 사건이 둘을 못 가른다. 겹쳐 놓고 둘 다
    # 같은 값으로 채우면 서로 어긋나는 사실이 조용히 만들어진다 — 안 읽는다.
    for 읽음 in 읽은절:
        for name in 읽음["채울자리"]:
            역할 = parser.placeholders.get(읽음["값"].get(name))
            if 역할 is not None and 역할 not in 역할조사:
                return None
    triples, 값, 자리, 채울자리, 빈자리, 호출, 프로그램단계 = [], {}, {}, {}, {}, [], []
    for index, 읽음 in enumerate(읽은절):
        prefix = "c%d_" % index
        뜻 = 읽음["뜻"]
        rows = 뜻.get("triples") or ([뜻["triple"]] if "triple" in 뜻 else [])
        triples += [_rename(row, prefix) for row in rows]
        # A direct clause emits its declared facts.  A clause that reused an
        # earlier learned action keeps that action as an actual call step;
        # its expanded triples above remain the stable explanatory meaning,
        # not a second state transition.
        steps = 읽음.get("프로그램단계") or [{"op": "emit", "triples": rows}]
        프로그램단계 += [_rename(step, prefix) for step in steps]
        값.update({prefix + k: v for k, v in 읽음["값"].items()})
        자리.update({prefix + k: v for k, v in 읽음["자리"].items()})
        빈자리.update({prefix + k: v for k, v in 읽음["빈자리"].items()})
        for call in 읽음.get("호출") or []:
            호출.append({**call,
                         "role_slots": {prefix + key: value for key, value in
                                        (call.get("role_slots") or {}).items()},
                         "values": {prefix + key: value for key, value in
                                    (call.get("values") or {}).items()}})
        for name, key in 읽음["채울자리"].items():
            역할 = parser.placeholders.get(읽음["값"].get(name))
            채울자리[prefix + name] = 역할조사.get(역할, key)
    쓴동사 = sorted({stem for 읽음 in 읽은절 for stem in (읽음.get("쓴동사") or ())})
    return {"뜻": {"triples": triples}, "값": 값, "자리": 자리,
            "채울자리": 채울자리, "빈자리": 빈자리, "호출": 호출,
            "프로그램단계": 프로그램단계,
            "쓴동사": 쓴동사}


def induce(parser, body, 배운것=None):
    """몸통을 이미 아는 문장꼴로 읽는다. 읽히면 쓸 수 있는 뜻틀을 준다.

    ``배운것`` 은 이 대화에서 **먼저 설명받은 동작**들이다. 사례로 안 읽히면
    그것들로 읽어 본다 — 배운 동작이 다른 설명의 재료가 되는 길이다.

    가장 적게 지운 자름을 고른다. 더 지울수록 말을 더 삼키기 때문이다.
    순서를 그대로 둔 자름을 먼저 다 보고, 그것으로 안 되면 순서를 바꿔 본다 —
    흔한 쪽을 먼저 보는 것이 값도 싸고, 덜 흔든 읽기를 고르는 길이기도 하다.
    """
    # 절로 나뉘는 몸통은 **조합**이다. 배운 동작 하나로 먼저 읽으려 들면 그 하나가
    # 몸통을 통째로 삼킨다 — `상대에게 베풀고, 상대가 나` 가 한 이름이 된다.
    if _clauses(body, parser.clause_grammar):
        return _compose(parser, body, 배운것)
    found = _read_body(parser, body, False)
    # 조사를 넘어 삼킨 자름이 나왔으면 순서를 바꾼 자름도 보고 더 나은 쪽을 쓴다.
    # 먼저 나온 것을 그냥 쓰면 `상자로 물건을` 이 한 이름으로 굳는다.
    if found is None or found[0][2]:
        other = _read_body(parser, body, True)
        if other is not None and (found is None or other[0] < found[0]):
            found = other
    배운읽기 = _from_rule(parser, body, 배운것)
    if found is None:
        return 배운읽기
    # **순서로 정하지 않고 겨룬다.** 넓은 사례 틀은 아무 말이나 한 이름으로 삼켜
    # 맞기 때문에, 먼저 보는 쪽이 이기면 배운 동작이 영영 안 쓰인다.
    # 조사를 덜 넘은 읽기가 옳은 읽기다.
    if 배운읽기 is not None and 배운읽기.get("삼킴", 0) < found[0][2]:
        return 배운읽기
    return found[1]


def _compile(parser, example, piece):
    """조각 사례의 틀. 몸통마다 다시 짓지 않는다."""
    cache = parser.__dict__.setdefault("_조각틀", {})
    key = (example["text"], piece["text"])
    if key not in cache:
        cache[key] = parser.compile(piece, parser.data.get("numerals", {}),
                                    parser.slot_particles)
    return cache[key]


def _read_body(parser, body, reorder):
    from numeral_semantics import parse_numeral
    particles = parser.case_particles
    groups = parser.slot_particles
    numerals = parser.data.get("numerals", {})
    best = None
    for example in parser.data["examples"]:
        # State facts and action-program examples are both legitimate
        # definition bodies.  The latter only declares a generic operation
        # shape; it does not name the action the user will teach.
        if not (asserted(example["meaning"]) or example["meaning"].get("program")):
            continue                # 물음도 뜻풀이도 몸통이 될 수 없다
        for piece, dropped, missing, reordered in _elisions(example, particles, groups, reorder):
            # A fully elided example leaves only a generic predicate tail
            # (for example, ``만드는``).  It has no typed role evidence and
            # would let an unrelated unknown verb masquerade as any newly
            # added domain action.  At least one retained semantic slot is
            # required for a learned definition body.
            if not piece["slots"]:
                continue
            # A retained role plus case marker alone (``내가`` / ``상대에게``)
            # is not a sentence body.  Its compiled capture can absorb an
            # arbitrary unknown verb after inflection normalisation.  Require
            # some non-slot, non-particle lexical material as well; this is a
            # structural guard shared by every pack example, not an action
            # word allowlist.
            literal = piece["text"]
            for value in piece["slots"].values():
                literal = literal.replace(str(value), "", 1)
            for particle in sorted(particles, key=len, reverse=True):
                literal = literal.replace(particle, "")
            if not literal.strip():
                continue
            patterns, meaning = _compile(parser, example, piece)
            for candidate in _finite(body, example, parser.inflection_grammar):
                for pattern in patterns:
                    match = pattern.fullmatch(candidate)
                    if not match:
                        continue
                    values = dict(match.groupdict())
                    # `하루가 연필` 을 한 이름으로 삼킨 자름은 **덜 좋은** 읽기지
                    # 못 읽는 것이 아니다. 잘라 버리면 `사과 상자` 같은 성한
                    # 이름까지 못 읽는다. 어느 자름이 옳은지는 겨뤄서 정한다.
                    삼킴 = sum(_marked(value, particles, groups) for value in values.values())
                    for name, annotated in piece["slots"].items():
                        if annotated.isdecimal():
                            values[name] = parse_numeral(values[name], numerals)
                    if any(value is None for value in values.values()):
                        continue
                    spans = _spans(piece)
                    자리 = {name: _particle_at(piece["text"], end, particles, groups)
                           for _s, end, name in spans}
                    자리 = {k: v for k, v in 자리.items() if v}
                    specificity = len(candidate) - sum(len(value) for value in match.groupdict().values())
                    # 적게 지운 것, 순서를 안 바꾼 것, 조사를 덜 넘은 것, 더 많이
                    # 못 박은 것 순.
                    score = (missing, reordered, 삼킴, -specificity)
                    if best is None or score < best[0]:
                        emitted = {"triples": [step for step in meaning.get("program", [])
                                                 if step.get("op") == "emit"]}
                        # ``뜻`` stays available to the old composition and
                        # conflict machinery; the runtime receives the full
                        # program separately and executes it once.
                        if emitted["triples"]:
                            emitted = {"triples": [triple for step in emitted["triples"]
                                                     for triple in step.get("triples", [])]}
                        else:
                            emitted = meaning
                        best = (score, {"뜻": emitted, "값": values, "자리": 자리,
                                        "채울자리": _open(values, 자리, parser.placeholders),
                                        "빈자리": dropped,
                                        "프로그램단계": deepcopy(meaning.get("program") or [])})
    return best


def _open(values, 자리, placeholders):
    """뜻풀이가 적어 둔 값 가운데 **자리말**인 것. 그 자리는 사건이 채운다.

        치우다는 물건을 상자로 옮기는 것이다
                 ^^^^ 자리말 — 물건이라는 이름의 물건이 아니다
                      ^^^^ 값 — 뜻풀이가 정한 곳

    자리인지 값인지는 **짜임으로는 안 갈린다.** `물건` 과 `상자` 는 문장에서
    똑같이 생겼다. 갈리는 것은 낱말의 성질이므로 언어팩이 낱말로 적는다.
    적히지 않은 낱말은 값으로 본다 — 사건이 딴 값을 대면 고르지 않고 묻는다.
    """
    return {name: key for name, key in 자리.items() if values.get(name) in placeholders}


def apply_rule(induced, 자리, 덮기=()):
    """사건이 짚은 자리로 뜻틀을 채운다. **못 채운 자리는 못 채웠다고 말한다.**

    자리 하나를 못 채웠다고 아무 일도 없었던 것이 아니다. `지연에게 베풀었다`
    는 누가 줬는지는 몰라도 무언가 일어났다고 말한다. 그것을 빈 사실 목록으로
    바꾸면 **해석 실패가 "변화 없음" 으로 둔갑한다** — 옛 값이 그대로 확정된다.
    그래서 둘을 갈라서 돌려주고, 못 채운 자리가 있으면 사실은 안 쓴다.
    """
    채울자리 = induced.get("채울자리", {})
    values, 충돌 = dict(induced["값"]), {}
    # 뜻풀이가 정한 값을 **사람이 그렇게 하라고 한 만큼만** 덮는다. 우리가 고르는
    # 것이 아니라 어디까지인지 물어서 받은 답이다.
    덮기 = dict(덮기 or {})
    for name, key in induced["자리"].items():
        if key in 덮기:
            values[name] = 덮기[key]
    for name in 채울자리:
        values.pop(name, None)                # 자리말은 값이 아니다. 비워 둔다
    # **자리말이 앉은 자리는 채울자리가 정한다.** 몸통에 적힌 조사를 그대로 쓰면
    # 두 절에 같은 자리말이 나와도 안 뒤집힌다 — `상대가 나에게` 의 `상대` 는
    # 앞절에서 `에게` 자리였으므로 여기서도 `에게` 로 채워야 한다.
    # 사건이 조사 하나에 준 값은 **그 조사를 비워 둔 자리**의 몫이다. 같은 조사에
    # 앉은 상수까지 그 값과 견주면, `물건을 상자로 옮기고 상자를 책상으로 옮기는`
    # 의 `상자` 가 사건의 `연필` 과 부딪친 것으로 잡힌다.
    열린조사 = set({**induced["빈자리"], **채울자리}.values())
    for name, key in {**induced["자리"], **induced["빈자리"], **채울자리}.items():
        if key not in 자리:
            continue
        if name in induced["빈자리"] or name in 채울자리 or key in 덮기:
            values[name] = 덮기.get(key, 자리[key])
        elif key not in 열린조사 and induced["값"].get(name) != 자리[key]:
            # 뜻풀이가 정한 값과 다른 값이다. 채우는 것이 아니라 바꾸는 것이므로
            # 말없이 어느 한쪽을 고르지 않는다.
            충돌[name] = {"뜻": induced["값"].get(name), "사건": 자리[key], "자리": key}
    빈자리 = {name: key for name, key in {**induced["빈자리"], **채울자리}.items()
             if name not in values}
    남은자리 = {key for key in 자리
             if key not in set(induced["자리"].values()) | set(induced["빈자리"].values())}
    # 자리말이 안 채워졌으면 그 자리는 **비워 둔 채로** 닿는 곳을 센다. 뜻풀이에
    # 적힌 `물건` 을 도로 넣으면 "물건이라는 것의 자리" 만 못 박고, 정작 무엇이
    # 움직였는지 모르는 채로 딴 값을 확정하게 된다.
    사실 = asserted(substitute(induced["뜻"], values))
    return {"사실": [] if (빈자리 or 충돌) else 사실, "빈자리": 빈자리,
            "충돌": 충돌, "남은자리": 남은자리, "닿는곳": 사실}


def asks(text, negation=None, verbs=None):
    """묻는 말인가. 설명받은 어간의 **묻기 전용 꼴**로 끝나면 묻는 말이다.

    물음표에만 기대면 안 된다 — `민수가 지연에게 베풉니까` 는 물음표가 없어도
    물음이고, 사건으로 읽으면 물어본 일이 실제로 일어난다.
    """
    words = text.strip().rstrip(".!?…").split()
    if not words:
        return False
    if negation and words[-1] in (negation.get("물음") or ()):
        return True
    return bool((verbs or {}).get(words[-1], {}).get("물음"))


def _chunkings(words, particles, groups, limit=12, elidable=()):
    """자리 나누기의 갈래들. 어느 자름이 옳은지 여기서는 못 정한다.

        사과 상자를   ->   [사][상자]   또는   [사과 상자]

    `사과` 의 `과` 가 조사인지 이름의 끝 글자인지는 이 낱말만 봐서는 안 갈린다.
    그러니 갈래를 다 내주고, **뜻풀이가 그 자리를 쓰는지**가 정하게 한다.
    """
    def walk(index, current, done):
        if len(done) > len(words):
            return
        if index == len(words):
            if not current:
                yield done
                return
            # 맨 끝에 조사 없이 남은 낱말은 **떨어진 조사** 자리로도 읽는다. 어느 조사가
            # 떨어질 수 있는지는 팩이 말한다(`생략조사`). 이미 찬 자리에는 안 놓는다.
            # 조사를 단 낱말이 하나라도 섞여 있으면 떨어진 조사가 아니라 자름이 틀린 것이다.
            # ponytail: `사과` 처럼 이름 끝이 조사와 겹치는 낱말은 여기서 못 읽는다.
            # 조사가 짚은 자리가 하나도 없으면 사건 꼴이 아니다 — `민수 아냐` 를 사건으로 안 읽는다.
            if not done or any(split_particle(word, particles, groups) for word in current):
                return
            for particle in elidable:
                key = particle_key(particle, groups)
                if all(k != key for k, _v in done):
                    yield done + [(key, " ".join(current))]
            return
        piece = split_particle(words[index], particles, groups)
        if piece is not None and piece[0]:
            value = " ".join(current + [piece[0]])
            if all(key != piece[1] for key, _v in done):
                yield from walk(index + 1, [], done + [(piece[1], value)])
        yield from walk(index + 1, current + [words[index]], done)

    out, 잘림 = [], False
    for reading in walk(0, [], []):
        if reading and reading not in out:
            out.append(reading)
        if len(out) >= limit:
            잘림 = True             # 다 못 봤다는 것을 숨기지 않는다
            break
    return [dict(reading) for reading in out], 잘림


def read_event(text, particles, groups, negation=None, verbs=None,
               plan=None, grammar=None, elidable=()):
    """조사가 자리를 짚고 남은 한 낱말이 움직임인 꼴. 사건은 이렇게 생겼다.

    **뜻을 몰라도 꼴은 안다.** 그래야 모르는 말을 만났을 때 "그 말을 모릅니다"
    라고 짚어 주고, 나중에 설명을 들으면 이어서 풀 수 있다. 뜻은 여기서
    정하지 않는다 — 쓰인 낱말을 그대로 돌려주고, 설명받은 어간과 잇는 일은
    활용표가 한다.

    꼴이 아닌 것은 안 읽는다. 앞 낱말이 조사를 안 달았으면(`단추 이야기는
    재밌다` 의 `단추`) 자리를 못 짚은 것이고, 못 짚으면 짐작하지 않는다.

    **묻는 말도 사건이 아니다.** 물음표가 없어도 그렇다 — `베풉니까` 는
    설명받은 어간의 물음꼴이므로 일어난 일이 아니다. 활용을 이을 때 어간만
    나르면 이 자리를 놓친다.

    자리를 어디서 끊을지는 여럿일 수 있다(`사과 상자를`). 갈래를 다 담아 두고
    고르는 일은 뜻풀이를 아는 쪽에 맡긴다.
    """
    words = text.strip().rstrip(".!?…").split()
    if not words or asks(text, negation, verbs):
        return None
    polarity, tail, modality = True, words[-1:], None
    # 아직 안 일어난 일. 꼴로 알아보고 **사실로 안 적는다.**
    if plan and len(words) > 2 and words[-1] in plan["맺음"]:
        어간 = _plan_stem(words[-2], verbs, plan, grammar)
        if 어간 is None:
            return None
        modality, tail, words = "planned", [어간], words[:-1]
    if negation and len(words) > 2 and words[-1] in negation["forms"]:
        stem = words[-2][:-len(negation["연결"])]
        if not words[-2].endswith(negation["연결"]) or not stem:
            return None
        polarity, tail, words = False, [stem], words[:-1]
    if len(words) < 2:
        return None
    # 떨어진 조사는 **아는 움직임** 앞에서만 읽는다. 모르는 끝말까지 받으면 사건이 아닌
    # 말(`관찰만 기록한다`)이 모르는 사건으로 남아 값을 막는다.
    if not any(word in (verbs or {}) for word in (text.strip().rstrip(".!?…").split()[-1], tail[0])):
        elidable = ()
    후보, 잘림 = _chunkings(words[:-1], particles, groups, elidable=elidable)
    if not 후보:
        return None             # 조사 없는 낱말이 남으면 자리를 못 짚은 것이다
    # 자름이 너무 많아 다 못 봤으면 그렇다고 적어 둔다. 남은 하나를 유일한
    # 해석처럼 쓰면, 못 본 자름이 옳았을 때 틀린 값을 조용히 확정하게 된다.
    event = {"verb": tail[0], "자리": 후보[0], "자리후보": 후보, "잘림": 잘림}
    if modality:
        event["modality"] = modality
    return event if polarity else {**event, "polarity": False}


def _plan_stem(word, verbs, plan, grammar):
    """`베풀` 처럼 매김꼴 미래로 적힌 말의 어간. **아는 어간만** 되돌린다."""
    from hangul import inflect
    for surface, found in (verbs or {}).items():
        stem = found["stem"] if isinstance(found, dict) else found
        try:
            꼴 = {form["text"] for tense in (grammar or {}).get("tenses", {})
                 for form in inflect(stem, tense, plan["연결"], grammar, kind="regular")}
        except ValueError:
            continue
        if word in 꼴:
            return stem
    return None
