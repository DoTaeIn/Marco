# -*- coding: utf-8 -*-
"""지식 그래프와 대화한다. 그래프에 있는 것만 골라 조립한다 — 지어내지 않는다.

    python 짓기.py 내폴더                   # 폴더 -> 지식그래프.json
    python 설명.py 내폴더/지식그래프.json    # 대화
    python 설명.py --draw 내폴더/지식그래프.json

논증 엔진(engine.py)과 나뉘어 있다. 이쪽은 판정하지 않는다. 설명한다.
"""
from functools import lru_cache
import io, json, os, re, sys
from collections import deque

from build import extract_concepts
from encoder import DEVICE, MODEL, _abs, _embed, _embed_all, _model, _embed_sub, _embed_sub_all, mask_numbers, split_fragments

def graphify_read(path, max_n=1200):
    """graphify graph.json -> 이 엔진이 쓸 수 있는 형태.

    graphify 는 그래프를 잘 짓지만 두 가지가 약하다. 자기 문서가 인정한다:
    노드 매칭이 문자열 포함이라 어휘가 어긋나면 0건이 되고, 답변은 LLM 이 쓴다.
    이 엔진은 그 두 자리를 임베딩 매칭과 선택형 응답으로 메운다.

    판정용 그래프가 아니므로 목표·요건이 없다. 설명만 한다."""
    raw = json.load(open(path, encoding="utf-8"))
    node, meta = {}, {}
    for n in raw.get("nodes", [])[:max_n]:
        name = n.get("label") or n.get("id")
        if not name:
            continue
        example = [name]
        for k in ("norm_label", "community_name", "summary", "description"):
            v = n.get(k)
            if v and isinstance(v, str) and v.lower() != name.lower():
                example.append(v)
        node[name] = example[:4]
        meta[name] = {"community": n.get("community_name"),
                      "file": n.get("source_file"),
                      "loc": n.get("source_location"),
                      "type": n.get("file_type")}
    by_id = {n.get("id"): (n.get("label") or n.get("id"))
            for n in raw.get("nodes", [])}
    edge = []
    for e in raw.get("links", []) + raw.get("edges", []):
        a, b = by_id.get(e.get("source")), by_id.get(e.get("target"))
        r = e.get("relation") or e.get("type") or "관련"
        if a in node and b in node:
            edge.append([a, r, b])
    return {"역할": "안내", "목표": None, "설명그래프": True,
            "임계값": {"A_MIN": 0.45, "OK_MIN": 0.58},
            "노드": node, "메타": meta, "엣지": edge, "무관층": {}}


def read_dialect(name=None):
    """말투를 파일에서 읽는다. 말은 엔진이 아니라 데이터다.

    조사·이음말·관계 말투·주어 생략 판단이 전부 한국어 규칙인데 파이썬에
    박혀 있으면 다른 언어를 쓸 때 엔진을 고쳐야 한다. 그래프를 바꿔 도메인을
    바꾸듯 말투 파일을 바꿔 언어를 바꾼다.

    KG_LANG 환경변수나 인자로 고른다. 기본은 styles/한국어.json 이다."""
    name = name or os.environ.get("KG_LANG", "한국어")
    path = name if name.endswith(".json") else os.path.join("styles", name + ".json")
    with open(_abs(path), encoding="utf-8") as f:
        phrase = json.load(f)
    phrase["_조사자리"] = (re.compile(r"([가-힣]) (%s)(?=[\s.,?!]|$)"
                                  % "|".join(phrase["조사짝"]))
                       if phrase.get("조사짝") else None)
    phrase["_띄운조사"] = (re.compile(r"([가-힣0-9)]) (%s)(?=[\s.,?!]|$)"
                                  % "|".join(phrase["붙일조사"]))
                       if phrase.get("조사붙임") and phrase.get("붙일조사") else None)
    phrase["_주어없음"] = re.compile(phrase["주어없음"]) if phrase.get("주어없음") else None
    phrase["_대화질문"] = (re.compile(phrase["대화질문"]) if phrase.get("대화질문") else None)
    phrase["_자세히"] = re.compile(phrase["자세히"]) if phrase.get("자세히") else None
    return phrase


dialect = read_dialect()
relation_phrase = dialect["관계말"]


def relation_sentence(relation, reward_obj, outgoing=True):
    template = relation_phrase.get(relation)
    if template:
        return template[0 if outgoing else 1] % reward_obj
    return dialect["관계말없음"] % (reward_obj, relation)


intent_table = dialect.get("의도표", [])


# 의도마다 '어떤 문장이 답인가' 가 다르다. 이 표지가 없으면 의도를 늘려도
# 답이 그대로다 — 판정 이름만 늘고 하는 일은 같아진다.
meaning_marker = dialect.get("뜻표지", {})


@lru_cache(maxsize=1)
def _intent_keys():
    """표의 열쇠를 활용꼴까지 펼친다.

    표에는 '어디서 쓰' 라고 적히는데 사람은 '어디서 써' 라고 친다. 겉꼴만
    대조하면 같은 말을 놓친다 — 말끝은 적어 두는 것이 아니라 문법에서
    만든다. 열쇠가 '<앞말> <한 글자>' 꼴일 때 그 한 글자를 어간으로 보고
    선언된 어미로 활용한다. 어간이 아니면 만들어진 꼴이 아무것도 안 맞아
    표가 그대로 동작한다.
    """
    import hangul
    grammar = dialect.get("활용", {})
    expanded = []
    for k, v in intent_table:
        forms = {"".join(k.split())}
        head, _, last = k.rpartition(" ")
        if head and len(last) == 1 and grammar:
            head = "".join(head.split())
            for ending in grammar.get("parsing_endings", []):
                try:
                    made = hangul.inflect(last, "present", ending, grammar, kind="regular")
                except Exception:
                    continue
                forms.update(head + form["text"] for form in made)
        expanded.extend((form, v) for form in forms)
    return tuple(expanded)


def intent(question):
    """질문이 무엇을 묻는지 고른다. 앞에 오는 것이 이긴다."""
    t = "".join(question.split())
    correct_ones = []
    for key, v in _intent_keys():
        i = t.find(key)
        if i >= 0:
            # 같은 자리에서 겹치면 긴 쪽이 이긴다. '어디' 가 '어디서 쓰' 를
            # 가로채면 위치를 묻는 것으로 오해한다.
            #
            # 문장 끝쪽에 붙은 표지는 앞의 것을 이긴다. 한국어는 무엇을 묻는지가
            # 끝에 온다 — '요건이랑 증거는 무슨 관계야' 에서 `요건`(0번 자리)이
            # `무슨 관계`(7번 자리)를 이겨 조건 질문으로 갔다. 앞에 있는 것은
            # 대개 물음의 **대상**이고 뒤에 있는 것이 물음의 **꼴**이다.
            tail = i + len(key) >= len(t) - 3
            correct_ones.append((0 if tail else 1, i, -len(key), v))
    return min(correct_ones)[3] if correct_ones else "정의"


def _adjacent(g):
    """엣지를 노드별로 한 번만 접어둔다.

    지식 그래프는 엣지가 37만 개다. 질문마다 전수 스캔하면 설명 한 번에
    166ms 가 든다 — 벡터 계산(16ms)보다 열 배 비싸다."""
    if "_인접" not in g:
        out_edges, in_edges = {}, {}
        for x, r, y in g["엣지"]:
            out_edges.setdefault(x, []).append((r, y))
            in_edges.setdefault(y, []).append((r, x))
        g["_인접"] = (out_edges, in_edges)
    return g["_인접"]


def linking_path(g, a, b, max_n=5, remove_relation=("같은조문",)):
    """두 노드 사이 최단 경로. 관계 이름을 그대로 들고 온다.

    '같은조문' 은 기본으로 뺀다. 한 대목에 함께 나왔다는 것뿐이라 두 홉만 타면
    아무 개념이나 이어진다 — 이어졌다는 말이 뜻을 잃는다."""
    out_edges, in_edges = _adjacent(g)
    def dests(n):
        return ([(r, y, True) for r, y in out_edges.get(n, ()) if r not in remove_relation] +
                [(r, x, False) for r, x in in_edges.get(n, ()) if r not in remove_relation])
    front, q = {a: None}, deque([a])
    while q:
        n = q.popleft()
        if n == b:
            break
        for r, m, mid in dests(n):
            if m not in front:
                front[m] = (n, r, mid)
                q.append(m)
    if b not in front:
        return None
    loc = []
    n = b
    while front[n]:
        p, r, mid = front[n]
        loc.append((p, r, n, mid))
        n = p
    loc.reverse()
    return loc if len(loc) <= max_n else None


def _passage_name(src):
    """'김치찌개 / 두부(두부)' -> '김치찌개 / 두부'. 괄호 반복을 없앤다."""
    m = re.match(r"^(.*?)\((.*)\)$", src)
    if m and m.group(1).rstrip().endswith(m.group(2)):
        return m.group(1).rstrip()
    return src


# 의도가 바라는 발췌의 꼴. build.꼴매기기 가 매긴 이름과 맞춘다.
_sense_form = {"정의": ("정의",), "방법": ("절차", "코드"), "이유": ("이유", "실측"),
         "조건": ("조건",), "쓰는곳": ("코드", "절차"), "시간": ("조건",),
         "주체": ("절차",)}


def pick_excerpt(g, name, question=None, meaning=None):
    """그 개념의 문장들 중 질문에 가장 가까운 것을 고른다.

    같은 개념이 여러 대목에 다른 정보로 나온다. '두부' 는 자기 절에서 정의이지만
    김치찌개 절에서는 '마지막에 넣어야 부서지지 않는다' 이다.
    질문을 보고 골라야 '언제 넣어?' 에 정의를 주는 일이 없다.

    후보가 한 노드분(보통 2~6문장)뿐이라 그때 인코딩해도 비용이 거의 없다.
    다만 한 문장씩 부르면 모델 호출 8번이다 — 한 번에 넣는다."""
    cand = (g["메타"].get(name) or {}).get("발췌") or []
    if isinstance(cand, str):                       # 옛 형식
        return {"글": cand, "곳": (g["메타"][name] or {}).get("file")}
    if not cand:
        return None
    if not question or len(cand) == 1:
        return cand[0]
    meaning = meaning or intent(question)
    marker = meaning_marker.get(meaning, ())
    # 지을 때 매겨 둔 발췌의 꼴을 쓴다. 같은 노드에 문장이 여덟 개 붙어 있어도
    # 지금까지는 전부 같은 종류라 `임계값이 뭐야` 와 `임계값 어떻게 정해` 가
    # 같은 답을 냈다. 의도에 맞는 꼴을 앞세운다.
    wanted_form = _sense_form.get(meaning, ())
    if len(cand) > 8:
        # 인코딩 비용은 후보 수에 그대로 비례한다. 8개로 자르되, 자르기 전에
        # 표지로 순서를 바꾼다 — 표지는 문자열 검사라 공짜다.
        blocker = [x for x in cand
                if (marker and any(t in x["글"] for t in marker))
                or (wanted_form and set(x.get("꼴") or ()) & set(wanted_form))]
        rest = [x for x in cand if x not in blocker]
        cand = (blocker + rest)[:8]
    # 답이 될 쪽을 속에 둔다. 뒤집어서 '이 발췌가 내 질문을 담고 있나' 로
    # 재봤더니 긴 발췌가 짧은 질문을 거저 담았다 — '고양이 키우고 싶다' 에
    # 도로교통법 제49조가 나왔다. 긴 쪽을 담는 쪽에 두면 길이가 곧 점수다.
    # 발췌에는 절차찾기 의 낱말 문 같은 별도 관문이 없으므로 보수적으로 둔다.
    v = _embed(question)
    V = _embed_sub_all([mask_numbers(x["글"]) for x in cand])
    best, score = cand[0], -1.0
    for x, xv in zip(cand, V):
        c = float(xv @ v)
        # 꼴이 맞으면 밀어준다. 자르지는 않는다 — 원하는 꼴이 하나도 없는
        # 노드가 있고, 그때 답을 아예 못 내면 손해다.
        if wanted_form and set(x.get("꼴") or ()) & set(wanted_form):
            c += 0.15
        # 표지 '개수' 에 비례한다. 모든 후보에 하나씩 있으면 보너스가 균일해져
        # 순위가 그대로다 — 실제로 그래서 답이 하나도 안 바뀌었다.
        # 0.025 로는 벡터를 못 이긴다. '개인정보 유출하면 처벌돼?' 에서
        # 벌칙 조문(제70조)이 개인정보를 네 번 부르는 정의 조문에 밀렸다.
        # 무엇을 묻는지는 문장이 얼마나 닮았는지보다 강한 신호다.
        caught_count = sum(1 for t in marker if t in x["글"])
        c += 0.06 * min(caught_count, 4)
        if c > score:
            best, score = x, c
    return best


_weak_relation = ("같은조문", "설명함")


def _strong_relation(pairs):
    """'같이 나왔다' 를 뺀 것.

    세어서 나온 관계(같은조문·설명함)와 판단해서 나온 관계(정의·상위·이유)를
    가른다. 법지식에서 앞의 것은 37만 개고 뒤의 것은 4천 개다. 안 가르면
    앞의 것이 뒤의 것을 통째로 덮어 '기간은 경과와 같은 대목에 나온다' 만 나온다."""
    return [x for x in pairs if x[0] not in _weak_relation]


def _is_definition(extracted, name):
    """이 발췌가 이 노드를 정의하는 문장인가.

    맞으면 인용이 낫다. 유(類)만 조립하면 종차(種差)가 통째로 빠진다 —
    '평균임금은 금액이다' 는 참이지만 아무것도 안 알려준다. 원문에
    '…총액을 총일수로 나눈 금액을 말한다' 가 있으면 그것을 그대로 옮긴다."""
    txt = (extracted or {}).get("글") or ""
    if name not in txt:
        return False
    return any(table in txt for table in ("말한다", "이란", "라 함은", "라고 한다"))


def assemble_relations(g, name, outgoing, incoming, m, scale=1):
    """판단해서 나온 관계로 답을 조립한다. 낱말은 전부 그래프 것이다.

    원문에 정의문이 없는 노드에서 인용은 조문 제목 조각을 낸다 — '근로계약'
    을 물으면 '제15조 제2장 근로계약.' 이 나왔다. 그럴 때 '근로계약은 계약을
    뜻한다' 가 낫다. 법지식 7,183노드 중 원문에 정의문이 있는 것은 987개
    (13.7%)뿐이라 이 자리가 나머지를 맡는다.

    말은 하나도 짓지 않는다. 상대는 그래프의 노드 이름이고 잇는 말은 말투
    파일의 `관계말` 이다.

    동어반복은 걸러낸다. `상위` 엣지는 접미사 규칙으로 뽑은 것이라 상대가
    제 이름 안에 들어 있다 — '사후설립은 설립의 한 갈래다' 는 참이지만
    낱말만 봐도 아는 것이라 아무것도 안 알려준다. 법지식에서 조립에 쓰인
    상위 2,504개가 **전부** 그랬다. 걸러내면 인용으로 넘어간다."""
    out_counted = [(r, y) for r, y in _strong_relation(outgoing) if not (r == "상위" and y in name)]
    incoming_counted = [(r, x) for r, x in _strong_relation(incoming) if not (r == "상위" and x in name)]
    if not out_counted and not incoming_counted:
        return None
    line = [fit_particle("%s 는 %s." % (
        name, " ".join(relation_sentence(r, y, True) for r, y in out_counted[:3 * scale])))] if out_counted else [name + "."]
    if incoming_counted:
        line.append(fit_particle(" ".join(
            relation_sentence(r, x, False) + "." for r, x in incoming_counted[:2 * scale])))
    # 근거를 남긴다. 다만 개념엣지는 [a, 관계, b] 세 칸이라 그 관계가 어느
    # 문장에서 나왔는지는 안 들고 있다. 지금은 노드의 정의처로 대신한다.
    place = (m.get("정의처") or [m.get("file")] or [None])[0]
    if place:
        line.append("— %s" % _passage_name(place))
    return " ".join(x for x in line if x)


def explain(g, name, meaning="정의", max_neighbor=5, question=None, scale=1):
    """노드를 묻는 방식에 맞춰 설명한다. 생성이 아니라 조립이다.

    조사는 조립한 부분에만 맞춘다. 인용한 원문은 한 글자도 건드리지 않는다 —
    '그 밖에 이 법에 따라' 의 '이' 를 조사로 보고 '가' 로 고친 적이 있다.

    배수는 '자세히' 라고 물었을 때 자를 자리를 몇 배로 늘릴지다. 이웃과
    발췌를 더 붙일 뿐 없던 것을 만들지 않는다 — 길게 답한다고 근거가
    묽어지면 안 된다. 감지어는 말투 파일에 있다."""
    max_neighbor = max_neighbor * scale
    out_edges, in_edges = _adjacent(g)
    outgoing, incoming = out_edges.get(name, []), in_edges.get(name, [])
    m = g["메타"].get(name, {})
    line = []

    join = lambda listing: fit_particle(" ".join(listing))

    if meaning == "위치":
        if m.get("file"):
            line.append("%s 는 %s%s 에 있다."
                      % (name, m["file"], (" " + m["loc"]) if m.get("loc") else ""))
        else:
            line.append("%s 의 위치는 그래프에 기록돼 있지 않다." % name)
        if m.get("community"):
            line.append("%s 묶음에 속한다." % m["community"])
        return join(line)

    if meaning == "이유":
        # 엣지에 근거가 없어도 원문에 이유를 적은 문장은 있을 수 있다. `왜` 를
        # 물었는데 "근거가 그래프에 없다" 만 내놓는 것은 아는 것을 안 꺼내는
        # 것이다. 지을 때 매긴 `이유`·`실측` 꼴을 먼저 본다.
        reason_stmt = [x for x in ((g["메타"].get(name) or {}).get("발췌") or [])
                  if isinstance(x, dict) and {"이유", "실측"} & set(x.get("꼴") or ())]
        if reason_stmt:
            extract = pick_excerpt(g, name, question, meaning) or reason_stmt[0]
            line.append(fit_particle("%s%s" % (extract["글"],
                      (" — " + _passage_name(extract.get("곳"))) if extract.get("곳") else "")))
            return "\n".join(line)
        grounds = [(r, x) for r, x in incoming if r == "rationale_for"] +               [(r, y) for r, y in outgoing if r == "rationale_for"]
        if grounds:
            line.append("%s 의 근거로 %s 가 기록돼 있다."
                      % (name, ", ".join(x for _, x in grounds)))
        else:
            line.append("%s 에 대한 근거는 그래프에 없다." % name)
            neighbor = [y for _, y in outgoing[:3 * scale]]
            if neighbor:
                line.append("대신 %s 와 이어져 있다." % ", ".join(neighbor))
        return join(line)

    if meaning == "쓰는곳":
        write = [(r, x) for r, x in incoming
                if r in ("imports", "imports_from", "calls", "references", "contains")]
        if write:
            line.append("%s 는 %s 에서 쓴다."
                      % (name, ", ".join("%s(%s)" % (x, r) for r, x in write[:max_neighbor])))
        else:
            line.append("%s 를 쓰는 곳이 그래프에 없다." % name)
        return join(line)

    if meaning == "이웃":
        near = outgoing[:max_neighbor] + incoming[:max_neighbor]
        if near:
            line.append("%s 는 %s 와 엮여 있다."
                      % (name, ", ".join(sorted({y for _, y in near}))))
        else:
            line.append("%s 는 연결된 것이 없다." % name)
        return join(line)

    def_at = m.get("정의처") or []
    extracted = pick_excerpt(g, name, question, meaning)

    # 발췌를 무조건 먼저 내보내면 관계말 경로에 영영 못 간다. 법지식 7,183노드가
    # 전부 발췌를 갖고 있어서 도달 노드가 0개였다 — 엣지 3,880개를 들고도 한 번도
    # 안 썼다. 그렇다고 관계를 늘 앞세우면 안 된다. 유(類)만 조립하면 종차가
    # 통째로 빠진다("평균임금은 금액이다" 는 참이지만 아무것도 안 알려준다).
    #
    # 원문에 이 노드의 정의문이 있을 때만 인용이 이긴다. 없으면 인용이 조문
    # 제목 조각을 낸다("제15조 제2장 근로계약.") — 그때는 조립이 낫다.
    if meaning == "정의" and not _is_definition(extracted, name):
        assemble = assemble_relations(g, name, outgoing, incoming, m, scale)
        if assemble:
            return assemble

    # 원문을 인용해서 답한다. '어디서 다룬다' 는 출처지 답이 아니다.
    # 지어내지 않고 그대로 옮긴다 — 여전히 선택이지 생성이 아니다.
    #
    # 뒤에 '함께 나오는 것: 회귀, 자체, 조립, 판례.' 를 붙이던 것을 뗐다.
    # 질문과 무관한 이웃 노드 이름이라 답을 읽는 데 방해만 됐다. 떼고 재니
    # 문서그래프 400노드에서 이름 100% / 가림 12% / 대목 74% 로 한 자리도
    # 안 움직였다 — 세 숫자 중 어느 것에도 기여하지 않던 군더더기다.
    # 이웃이 궁금하면 물으면 된다. '뭐랑 엮여' 가 '이웃' 뜻으로 간다.
    if extracted and extracted.get("글"):
        source_text = extracted["글"]
        line = []
        where = _passage_name(extracted.get("곳") or (def_at or [m.get("file")])[0] or "")
        every = len((m.get("발췌") or []))
        if where:
            line.append("— %s%s" % (where,
                      " 외 %d곳" % (every - 1) if every > 1 else ""))
        return (source_text + " " + join(line)).rstrip()

    if def_at:
        line.append("%s 는 %s 에서 다룬다%s."
                  % (name, _passage_name(def_at[0]),
                     " (외 %d곳)" % (len(def_at) - 1) if len(def_at) > 1 else ""))
        handled = [y for r, y in outgoing if r == "설명함"][:5 * scale]
        if handled:
            line.append("그 대목은 %s 를 함께 다룬다." % ", ".join(handled))
        return join(line)

    head = name
    if m.get("community"):
        head += " 는 %s 묶음에 속한다" % m["community"]
    elif m.get("type"):
        head += " 는 %s 다" % m["type"]
    else:
        head += " 다"
    if m.get("file"):
        head += " (%s%s)" % (m["file"], (" " + m["loc"]) if m.get("loc") else "")
    line.append(head + ".")
    # 판단해서 나온 관계가 있으면 그것만 쓴다. 안 그러면 '같은조문' 37만 개가
    # 앞자리를 다 차지해 '기간은 경과와 같은 대목에 나온다' 만 나온다.
    outgoing = _strong_relation(outgoing) or outgoing
    incoming = _strong_relation(incoming) or incoming
    if outgoing:
        line.append(" ".join(relation_sentence(r, y, True) + "." for r, y in outgoing[:3 * scale]))
    if incoming:
        line.append(" ".join(relation_sentence(r, x, False) + "." for r, x in incoming[:2 * scale]))
    if not outgoing and not incoming:
        line.append("연결된 것이 없다.")
    return join(line)


def _link_form(phrase):
    """종결형을 연결형으로. '들어간다' -> '들어가고'.

    관계말 표에 연결형을 따로 적지 않아도 되게 규칙으로 만든다.
    해라체 종결어미 '-는다/-ㄴ다/-다' 는 규칙적이라 이 몇 줄이면 된다.
      있다 -> 있고       (다 를 떼고 고)
      들어간다 -> 들어가고 (간 의 받침 ㄴ 을 떼고 고)
      넣는다 -> 넣고     (는다 를 떼고 고)

    언어마다 형태가 달라 규칙 자체는 코드로 남고, 어느 규칙을 쓸지는
    말투 파일의 '이음규칙' 이 고른다. 한국어가 아니면 그대로 둔다 —
    영어처럼 이음말로만 잇는 언어는 어형이 안 바뀐다."""
    if dialect.get("이음규칙") != "한국어":
        return phrase
    if phrase.endswith("는다") and len(phrase) > 2:
        return phrase[:-2] + "고"
    if phrase.endswith("다") and len(phrase) > 1:
        import hangul
        front = phrase[:-1]
        if hangul.batchim(front) == "ㄴ":
            return hangul.strip_batchim(front) + "고"
        return front + "고"
    return phrase


def explain_path(g, loc):
    """경로를 문장으로. 각 홉의 관계를 그대로 읽는다.

    홉마다 주어를 다시 쓰고 '그리고' 로만 이으면 늘어진다. 한국어는 앞 홉의
    도착이 다음 홉의 출발이면 주어를 생략하고 연결어미로 잇는다.
      전: 두부 는 김치찌개 에 들어간다 그리고 김치찌개 는 신김치 가 들어간다
      후: 두부 는 김치찌개 에 들어가고, 신김치 가 들어가는데
    이음말은 관계에 따라 고른다 — 인과면 '그래서', 예외면 '다만'."""
    chunk = []
    for i, (p, r, n, mid) in enumerate(loc):
        phrase = relation_sentence(r, n, mid)
        # 홉마다 주어가 바뀌므로 생략하면 안 된다. 'A는 B를 대신할 수 있고,
        # 그래서 C로 이어집니다' 는 A 가 C 로 이어진다고 읽힌다 — 실제로는
        # B 가 C 로 이어진다. 짧아지는 대신 뜻이 틀리면 그건 개선이 아니다.
        chunk.append((dialect["주어틀"] % p) + (_link_form(phrase) if i < len(loc) - 1 else phrase))
    return dialect["이음표"].join(chunk) + dialect["마침표"]


def prepare_knowledge(g):
    """설명 그래프에 벡터를 붙인다. 개념망이 있으면 그것으로 어휘를 넓힌다.

    노드 7천 개를 매번 인코딩하면 그래프 여는 데 23초가 걸린다. 게임의 NPC 나
    터미널 도구로 쓰려면 그 시간이 곧 시작 지연이다. engine.py 가 하던 대로
    내용 해시를 키로 디스크에 캐시한다 — 그래프를 고치면 해시가 바뀌어
    자동으로 다시 만들어진다."""
    import hashlib
    import numpy as np
    sub = {}
    for a, r, b in g.get("개념엣지", []):
        if r == "상위":
            sub.setdefault(b, []).append(a)
    names = list(g["노드"])
    sentence, span = [], []
    for n in names:
        example = list(g["노드"][n])
        # '기각' 을 물으면 '공소기각' 도 걸리게 한다. 상위어는 하위어의 표현을
        # 함께 들고 있어야 사람이 쓰는 말에 닿는다.
        example += [x for x in sub.get(n, [])[:8] if x not in example]
        span.append((len(sentence), len(sentence) + len(example)))
        sentence += [mask_numbers(x) for x in example]
    key = hashlib.sha1(("\n".join(sentence) + MODEL).encode("utf-8")).hexdigest()[:16]
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".vec_설명_%s.npz" % key)
    # 압축하지 않고 저장하면 mmap 으로 열 수 있다. 7,195노드 벡터가 28.5MB 인데
    # 통째로 램에 올릴 이유가 없다 — 한 번에 보는 것은 행렬 한 판뿐이다.
    # docs/ko/direction.md 의 층 구조가 원래 이것을 노렸다(SSD 순차 I/O, 콜드 66ms).
    V = None
    if os.path.exists(cache):
        try:
            V = np.load(cache, allow_pickle=False, mmap_mode="r")["V"]
            if len(V) != len(sentence):
                V = None
        except Exception:
            V = None                       # 캐시가 깨졌으면 그냥 다시 만든다
    if V is None:
        V = np.array(_model().encode(sentence, normalize_embeddings=True,
                                     batch_size=64, show_progress_bar=False))
        try:
            np.savez(cache, V=V)            # 압축하면 mmap 이 안 된다
        except OSError:
            pass
    g["vec"] = {n: V[i:j] for n, (i, j) in zip(names, span)}
    # 노드마다 따로 곱하면 7,195번 파이썬 루프다. 재보니 질문 하나에 284ms
    # 이고 프로파일에 ndarray.max 가 질문 셋에 43,188번 찍혔다. V 는 이미
    # 한 판의 행렬이므로 한 번에 곱하고 구간마다 최댓값만 집으면 된다.
    # 답은 한 자리도 안 바뀐다 — 같은 곱셈을 순서만 바꿔 하는 것이다.
    g["_V"] = V
    g["_이름들"] = names
    g["_시작"] = np.array([i for i, _j in span])
    # 묶음(community)별 노드 자리. 아직 답을 고르는 데 쓰지 않는다.
    #
    # 노드 고르기에 층을 씌워 봤다 — 묶음마다 상위 셋의 평균으로 어느
    # 문서 이야기인지 먼저 정하고 그 안에서만 겨루게. 법지식 982물음에서
    # 가림 134/982, 대목 127/982 로 **한 자리도 안 바뀌었다**. 층은
    # 실제로 골랐는데(60개 중 36개) 결과가 같았다.
    #
    # 이유는 _발췌찾기 의 주석에 이미 적혀 있었다. 노드 고르기는 병목이라
    # 판정돼 이미 우회된 길이다(노드 경유 1~3% 대 직접 검색 17%). 안 쓰는
    # 길을 좁혀 봐야 답이 안 변한다. 층을 쓰려면 _발췌찾기 쪽에 씌워야
    # 하는데, 거기는 발췌 전부를 한 행렬로 들고 있어 층이 줄여 줄 것이
    # 무엇인지부터 다시 재야 한다.
    pos = {}
    for i, n in enumerate(names):
        c = (g["메타"].get(n) or {}).get("community")
        if c:
            pos.setdefault(c, []).append(i)
    g["_층"] = {c: np.array(v) for c, v in pos.items() if len(v) >= 3}
    return g


# 엣지를 문 찾기에 쓸 때의 값. **기본은 0 이다 — 지금은 켜도 손해다.**
#
# 엣지가 2만 개 있는데 답을 고르는 데 한 번도 안 쓰이고 있어서 넣어 봤다.
# 이웃 상위 셋의 평균을 더하면 원점수 1등이 68 -> 70/96 으로 오른다. 그런데
# 파이프라인 전체로는 65 -> 65 로 그대로고, 관문을 다 끄면 오히려 69 -> 66
# 으로 떨어진다. 후보 다섯의 명단이 바뀌면서 `_숙고` 가 더 나쁘게 고른다.
# 질문당 12.3 -> 13.3 ms 다. 이득 없이 8% 느려지므로 꺼 둔다.
#
# 코드를 남기는 이유는 원점수가 실제로 좋아지기 때문이다. 답 고르기가
# 거부권 구조에서 가산 구조로 바뀌면(HANDOFF §0.0005) 이 항이 살아날 자리다.
# 그때 `KG_NEIGHBOR=0.6` 으로 다시 재면 된다.
neighbor_weight = float(os.environ.get("KG_NEIGHBOR", "0"))
neighbor_width = int(os.environ.get("KG_NEIGHBOR_WIDTH", "64"))
neighbor_count = 3


def _neighbor_table(g):
    """노드마다 이웃 자리를 한 표에 담아 둔다. 질문마다 다시 만들지 않는다.

    `설명함` 만 쓴다. `같은조문` 은 한 대목에 함께 나왔다는 것뿐이라 두 홉만
    타면 아무 개념이나 이어진다 — 잇는길 이 그것을 기본으로 빼는 이유와 같다.

    이웃이 359개인 노드도 있는데 평균은 12.6개다. 표를 최대치에 맞추면
    질문당 3.21ms 인데, 64개로 자르면 0.77ms 이고 적중은 같다(70/96).
    자를 때는 **이웃이 적은 쪽**을 남긴다 — 이웃이 많은 개념은 흔해서
    신호가 약하다. IDF 와 같은 발상이다."""
    if "_이웃표" in g:
        return g["_이웃표"]
    import numpy as np
    names = g.get("_이름들")
    if not names:
        g["_이웃표"] = None
        return None
    pos = {n: i for i, n in enumerate(names)}
    neighbor = {}
    for a, r, b in g.get("엣지", ()):
        if r != "설명함":
            continue
        ia, ib = pos.get(a), pos.get(b)
        if ia is None or ib is None:
            continue
        neighbor.setdefault(ia, set()).add(ib)
        neighbor.setdefault(ib, set()).add(ia)
    if not neighbor:
        g["_이웃표"] = None
        return None
    degree = {i: len(v) for i, v in neighbor.items()}
    N = len(names)
    width = min(neighbor_width, max(len(v) for v in neighbor.values()))
    table = np.full((N, width), N, dtype=np.int32)      # N 은 padding 자리(점수 0)
    for i, this in neighbor.items():
        picked = sorted(this, key=lambda j: degree.get(j, 0))[:width]
        table[i, :len(picked)] = picked
    g["_이웃표"] = table
    return table


def _all_scores(g, v):
    """노드 전부의 점수를 한 판에. 노드 순서는 g["_이름들"] 과 같다.

    이름이 얼마나 닮았나에 더해 **이웃이 얼마나 걸렸나**를 본다. 엣지가
    2만 개 있는데 답을 고르는 데는 한 번도 안 쓰이고 있었다 — 골라 놓고
    설명할 때만 썼다. 이웃 상위 셋의 평균을 더하면 1등 적중이 68 -> 70/96
    으로 오른다. 이웃 '전체 평균' 은 오히려 떨어뜨린다(67/96) — 이웃이
    스물이면 관계없는 것이 신호를 희석한다. 걸린 몇만 봐야 한다."""
    import numpy as np
    V = g.get("_V")
    if V is None:                          # 옛 그래프(캐시를 안 거친 것)
        return None
    pt = np.maximum.reduceat(V @ v, g["_시작"])
    table = _neighbor_table(g) if neighbor_weight else None
    if table is None:
        return pt
    long = np.concatenate([pt, [0.0]]).astype(np.float32)
    neighbor_score = long[table]
    top = (np.partition(neighbor_score, -neighbor_count, axis=1)[:, -neighbor_count:]
            if table.shape[1] > neighbor_count else neighbor_score)
    return pt + neighbor_weight * (top.sum(1) / neighbor_count)



# 부정 표지. 낱말 **바로 뒤**에 붙어야 그 낱말을 부정한다.
# '근거 없이' 는 근거를 부정하지만 '근거가 왜 없으면 안 되나' 의 '없으면' 은
# 근거를 부정하지 않는다 — 사이에 다른 말이 끼면 딴 것을 부정하는 것이다.
# 부정 표지와 복합어 판정. **둘 다 껐다 — 재보니 해로웠다.**
#
#   둘 다 끔   안 65/96 · 부정 갈래 3/4
#   부정만 켬  안 63/96 · 부정 갈래 1/4
#   복합만 켬  안 64/96
#   둘 다 켬   안 62/96
#
# 부정: '거짓말은 안 하나' 에서 거짓말을 빼면 맞을 줄 알았다. 그런데
# '증거가 없으면 왜 결론이 안 나오나' 는 증거가 부정당했어도 **증거가
# 주제다.** 한국어에서 'X 가 없으면' 은 여전히 X 에 대한 물음이다.
# 부정은 주제를 바꾸지 않는다.
#
# 복합: '탈옥 저항성' 에서 둘 중 하나를 임의로 고르지 말고 벡터에 넘기면
# 나을 줄 알았다. 탈옥은 고쳐졌지만 '증거 노드는 어떻게 표시하나요' 가
# `표시` 로 새면서 더 잃었다.
#
# 그래서 이 두 물음의 진짜 원인은 따로다 — `거짓말`·`근거`·`이유`·`기계`
# 처럼 **흔한 낱말이 노드로 잡혀** 진짜 개념(환각)을 가린다. 고칠 곳은
# 여기가 아니라 build.py 의 개념 뽑기이거나, 낱말이 얼마나 특정한지를
# 아는 표다.
no_negation = os.environ.get("KG_NEG", "0") == "0"
no_compound = os.environ.get("KG_CMP", "0") == "0"
_no_marker = re.compile(r"^(?:은|는|이|가|을|를|도|만)?\s*(?:안|못|없|않)")


def _was_negated(question, pos, length):
    """질문에서 그 낱말 바로 뒤가 부정인가.

    '거짓말은 안 하나' 를 물으면 주제는 거짓말이 아니다. 거짓말을 **안**
    한다는 이야기라 답해야 할 곳은 환각이다. 그런데 이름이 그대로 있다는
    이유로 거짓말이 이겼다. 실제로 부정이 든 물음 9개 중 4개가 틀렸고
    그중 3개가 이 모양이었다 — 맞는 노드는 이미 후보 안에 있었다."""
    rear = question[pos + length:pos + length + 6]
    return bool(_no_marker.match(rear))


def _is_attached(question, a, b):
    """두 이름이 질문에서 붙어 한 덩어리를 이루나. '탈옥 저항성' 처럼."""
    attach = "".join(question.split())
    return (a + b) in attach or (b + a) in attach


def _name_as_is(g, question, exclude=None):
    """질문에 노드 이름이 그대로 들어 있으면 그것을 쓴다.

    개념망으로 상위어가 하위어의 표현을 들고 있으면 '공소기각' 을 물었는데
    '기각' 이 답한다. 자기 이름이 질문에 있으면 자기가 이겨야 한다."""
    t = "".join(question.split())
    # 공백을 지운 자리에서 원문 자리로 돌아오는 표. 경계 판정은 원문에서 해야 한다 —
    # 지운 문자열에서 앞 글자를 보면 '국가에 손해배상' 의 '손해배상' 이
    # 앞이 '에' 라는 이유로 낱말 중간 취급을 받아 통째로 사라진다.
    pos = [i for i, ch in enumerate(question) if not ch.isspace()]
    matched = []
    for n in g["노드"]:
        if n == exclude or len(n) < 2:
            continue
        key = "".join(n.split())
        i = t.find(key)
        # 앞 글자가 한글이면 낱말 중간을 자른 것이다.
        # '해고가' 안에서 '고가' 를 뽑으면 엉뚱한 노드로 간다.
        while i >= 0:
            front = pos[i] - 1
            # 원문에서도 붙어 있어야 한다. 공백을 지운 자리에서 찾으면
            # '해고 예고 기간' 안에서 '예고기간'(행정절차법)이 걸린다.
            # 이름 자체에 공백이 있는 노드(법 이름)는 예외다.
            joined = pos[i + len(key) - 1] - pos[i] == len(key) - 1
            if (joined or key != n) and (front < 0 or not ("가" <= question[front] <= "힣")):
                # 바로 뒤가 부정이면 그 낱말은 주제가 아니다.
                if no_negation or not _was_negated(question, pos[i], len(key)):
                    matched.append(n)
                break
            i = t.find(key, i + 1)
    if not matched:
        return []
    # 붙어 한 덩어리를 이루는 두 이름은 어느 하나를 골라 쓰면 안 된다.
    # '탈옥 저항성' 은 탈옥도 저항성도 아니고 그 덩어리다. 덩어리 이름의
    # 노드가 따로 있으면 그것을 쓰고('마진 붕괴'), 없으면 이 문을 통째로
    # 비워 벡터 쪽에 넘긴다 — 임의로 하나 고르는 것보다 근거가 많다.
    block = [n for n in matched
              if any(m != n and n != m and _is_attached(question, n, m)
                     and (n in m or m in n) for m in matched)]
    attached_pair = [(a, b) for a in matched for b in matched
              if a != b and a not in b and b not in a and _is_attached(question, a, b)]
    if attached_pair and not block and not no_compound:
        whole = {a + b for a, b in attached_pair} | {a + " " + b for a, b in attached_pair}
        came = [n for n in matched if n in whole]
        if came:
            matched = came
        else:
            packed = {x for pair in attached_pair for x in pair}
            other = [n for n in matched if n not in packed]
            matched = other                      # 덩어리를 못 대면 이 문은 포기한다
    if not matched:
        return []
    v = _embed(question)
    # 긴 이름이 먼저다(더 구체적이다). 같은 길이면 질문에 가까운 쪽 —
    # '해고 절차' 에서 둘 다 두 글자다.
    return sorted(matched, key=lambda n: (-len(n), -float((g["vec"][n] @ v).max())))


def _jamo(phrase):
    """한글을 자모로 푼다. 오타는 대개 자모 하나 차이라 글자 단위로는 안 보인다.
    '해고' 와 '해구' 는 글자로 보면 완전히 다르지만 자모로 보면 ㅗ/ㅜ 하나다."""
    import hangul
    return hangul.jamo_index(phrase)


def _jamo_dist(a, b, max_n=2):
    """자모 단위 편집거리. 멀면 일찍 포기한다."""
    x, y = _jamo(a), _jamo(b)
    if abs(len(x) - len(y)) > max_n:
        return max_n + 1
    d = list(range(len(y) + 1))
    for i, p in enumerate(x, 1):
        front, d[0] = d[0], i
        for j, q in enumerate(y, 1):
            front, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, front + (p != q))
        if min(d) > max_n:
            return max_n + 1
    return d[-1]


def fix_typo(g, phrase, max_dist=1):
    """그래프가 아는 말 중 자모 하나 차이인 것. 없으면 None.

    재보니 오타 8건이 전부 자모거리 1 이고, 진짜 딴 말(고양이·피카츄)은
    6 이상이었다. 그래서 1 로 자르면 오타만 잡고 딴 얘기는 안 건드린다.

    후보는 길이가 비슷하고 첫 글자 초성이 같은 것만 본다 — 전부 재면
    노드 7천 개에 대해 매번 편집거리를 돌게 된다."""
    known_words = g.get("_아는말")
    if known_words is None:
        known_words = {}
        for n in g["노드"]:
            known_words.setdefault(len(n), []).append(n)
        # 흔한 것부터 본다. '해구' 는 '해고' 와도 '해부' 와도 자모 하나
        # 차이라 순서를 안 정하면 아무거나 걸린다. 문서에 자주 나오는 쪽이
        # 오타의 원래 말일 가능성이 높다.
        weight = {n: (g["메타"].get(n, {}).get("빈도") or 0) for n in g["노드"]}
        for L in known_words:
            known_words[L].sort(key=lambda n: -weight.get(n, 0))
        g["_아는말"] = known_words
    if not phrase or len(phrase) < 2:
        return None
    # 조사가 붙은 채로 오면 못 찾는다 ('해구가' 는 노드가 아니다).
    # 뒤에서 한 글자씩 떼어 보면서 아는 말에 닿는지 본다.
    for end in range(len(phrase), max(len(phrase) - 2, 1), -1):
        piece = phrase[:end]
        best, pt = None, max_dist + 1
        for L in (len(piece) - 1, len(piece), len(piece) + 1):
            for n in known_words.get(L, ()):
                d = _jamo_dist(piece, n, max_dist)
                if d < pt:                # 같은 거리면 앞엣것(더 흔한 것)이 이긴다
                    best, pt = n, d
                    if d == 0:
                        break
        if best and pt > 0:               # 거리 0 이면 오타가 아니라 아는 말이다
            return best
    return None


# 주제를 글자로 지우면 조사가 홀로 남는다. '공통층이랑 사례층은 뭐가 달라'
# 에서 `공통층` 을 빼면 `이랑` 이 남고, 그것이 명사로 잡혀 '이랑을 모른다'
# 로 거절된다. 실제로 관계를 묻는 물음 여럿이 이것 때문에 미지였다.
# 개념뽑기 는 멀쩡하다 — 지우는 쪽이 만든 찌꺼기다.
_bare_particle = frozenset("""이랑 랑 하고 과 와 이며 이고 라든지 든지 이나 나
    에서 에게 한테 부터 까지 보다 처럼 만큼 대로 조차 마저 밖에""".split())


def _unknown_words(g, question, topic, max_word=4, min_vocab=300, mix=0.4):
    """걸린 노드와 질문틀을 빼고, 이 코퍼스가 모르는 명사. 남으면 딴 얘기다.

    임베딩만 보면 '단어가 들어 있다' 와 '그것을 묻는다' 를 구별 못 한다.
    '주말에 영화 볼까' 가 저작권법의 '영화' 노드에 0.643 으로 붙어서
    영화상영관 정의 조항이 답으로 나왔다. 그래프에 영화가 있는 것은 맞지만
    묻는 사람은 저작권을 묻지 않았다.

    딴 얘기의 증거가 되는 것은 **명사**다 — 주말·고양이·피카츄. 서술어는
    아니다. 그래서 글자로 자르지 않고 코퍼스를 지을 때 쓴 `개념뽑기` 를
    그대로 되쓴다. 같은 잣대로 뜯어야 같은 것을 안다고 말할 수 있다.
    글자로 자르면 활용을 못 넘는다 — '빨라졌어' 는 원문의 '빨라진다' 와
    글자가 안 맞고, 조사를 떼자고 두 글자까지 깎으면 '불확정성' 이
    '불확실' 에 붙는다. 형태소는 둘 다 안 겪는다.

    견주는 자리는 `어휘` 다. 노드는 `최소` 로 걸러지고 발췌는 대목마다
    하나뿐이라 둘 다 코퍼스가 아는 말의 목록이 못 된다 — 한 번만 나온
    '매니저' 를 모른다고 하면 멀쩡한 물음이 거절된다.

    두 가지를 안 걸면 회귀가 난다.
      비율  긴 글은 모르는 말이 섞이는 것이 정상이다. 안 두면 원문 문장이
            통째로 거절되어 채점이 56% -> 12% 로 무너진다.
      규모  아는 말이 얼마 없는 그래프에서는 '없는 말' 이 아무 뜻도 없다."""
    known = g.get("_앎")
    if known is None:
        known = set(g.get("어휘") or ())
        if not known:                      # 어휘를 안 들고 있는 옛 그래프
            known = set(g["노드"]) | {w for _n, m in g["메타"].items()
                                   for x in m.get("발췌", ())
                                   for w in extract_concepts(x.get("글", ""))}
        g["_앎"] = known
    if len(known) < min_vocab:
        return []
    template = dialect.get("질문틀") or []
    other = re.sub(re.escape(topic), " ", question) if topic else question
    phrase = [w for w in extract_concepts(other)
          if not any(t in w or w in t for t in template) and w not in _bare_particle]
    unknown = [w for w in phrase if w not in known]
    # 긴 글은 모르는 말이 '섞이는' 것이 정상이다 — 섞인다는 것은 일부라는
    # 뜻이지 낱말 개수 문제가 아니다. 개수로 끊으면 말로 하는 물음은 쉽게
    # 다섯을 넘어 문이 통째로 없어진다('관측하면 상태가 하나로 정해지는
    # 이유가 뭐야' 는 모르는 말 둘을 달고도 그냥 지나갔다).
    if len(phrase) > max_word and len(unknown) < mix * len(phrase):
        return []
    return unknown


def _deliberate(g, txt, cand, memory=None):
    """후보를 각각 그래프로 밀어보고 결과가 서는 쪽을 고른다.

    지금까지는 이름이 가장 가까운 노드 하나를 집고 끝냈다. 그런데 정답이
    1등이 아니라 5등 안에 있는 경우가 훨씬 많다 — 재보니 1등 3%, 상위 5 안
    7% 였다. 그 사이가 숙고로 회수할 수 있는 몫이다.

    생성이 아니라 검증이다. 후보마다 '그 노드의 발췌가 이 질문에 실제로
    답하는가' 를 보고 가장 잘 답하는 쪽을 고른다. 이름이 비슷한 것과
    답이 되는 것은 다르다.

    후보가 붙어 있을수록(어려운 질문일수록) 볼 것이 많아지므로, 난이도에
    따라 계산이 느는 성질이 공짜로 따라온다."""
    # 여기서는 질문이 속이고 발췌가 담이다 — '이 발췌가 내 질문을 담고 있나'.
    # 발췌를 속에 두면 '발췌가 질문에 얼마나 덮이나' 가 되어, 짧은 발췌를 가진
    # 노드가 그냥 이긴다. 실제로 '비슷한 말끼리 묶어주나요' 가 개념망(0.691)을
    # 제치고 `무한` 으로, '법 말고 다른 분야' 가 도메인(0.667)을 제치고 `문법`
    # 으로 갔다. 긴 발췌가 짧은 질문을 거저 담는 위험은 _발췌찾기 에서 실제로
    # 겪었지만 여기는 다르다 — 숙고는 문턱을 정하지 않는다. 이미 뽑힌 후보
    # 다섯 중 누구를 고를지만 바꾼다.
    v = _embed_sub(txt)
    # 후보마다 발췌를 하나씩 인코딩하면 질문 하나에 모델을 서른 번 부른다.
    # 프로파일에서 torch.linear 가 시간의 75% 였다. 전부 모아 한 번에 넣는다.
    group, pos = [], {}
    for n in cand:
        excerpt = [x.get("글", "") for x in g["메타"].get(n, {}).get("발췌", ())
                if len(x.get("글", "")) > 10][:6]
        if excerpt:
            pos[n] = (len(group), len(group) + len(excerpt))
            group += excerpt
    vec = _embed_all(group)
    # 발췌 점수만으로 1등을 갈아치우면 안 된다. 발췌는 **원문 문장**이라
    # 사람이 노드에 가르쳐 넣은 표현이 거기 없다 — 노드 고르기는 말 예시를
    # 보고 배우는데 숙고는 그것을 못 보고 뒤집어 버린다. 실제로 '비슷한
    # 말끼리 묶어주나요' 가 개념망(이름 0.691)을 1등으로 올려놓고도 숙고에서
    # `기억` 으로, '법 말고 다른 분야에도' 가 도메인(0.667)에서 `단어` 로 갔다.
    #
    # 그래서 이름 점수를 더해 놓고 발췌는 그 위의 결선 투표로만 쓴다. 재보니
    # 두 인코더 모두 이쪽이 낫고 근거 없는 답이 늘지도 않았다.
    #   문자   안 61/96 -> 66/96 (바꿔말 2/20 -> 6/20), 밖 오답 4/62 그대로
    #   신경망 안 58/96 -> 65/96,                        밖 오답 9/62 그대로
    # 가중치는 0.0~2.0 어디로 둬도 한 줄도 안 바뀐다 — 이 그래프에서 발췌
    # 신호는 순위를 못 가른다. 그래도 남겨 둔다. 발췌가 실제로 가르는
    # 코퍼스에서는 이 항이 원래 하던 일(1등 3% / 상위 5 안 7%)을 한다.
    name = _embed(txt)
    best, score = None, -1e9
    for n in cand:
        s2 = float((g["vec"][n] @ name).max())
        if n in pos:
            i, j = pos[n]
            s2 += float((vec[i:j] @ v).max())
        s2 += (memory.bonus(n) if memory else 0.0)
        if s2 > score:
            best, score = n, s2
    return best, score


def _cands(g, txt, count=5, exclude=None):
    """이름이 가까운 노드 상위 몇 개."""
    v = _embed(txt)
    every = _all_scores(g, v)
    if every is None:
        pt = [(float((g["vec"][n] @ v).max()), n)
              for n in g["노드"] if n != exclude]
    else:
        pt = [(float(c), n) for c, n in zip(every, g["_이름들"]) if n != exclude]
    pt.sort(reverse=True)
    return [n for _c, n in pt[:count]], (pt[0][0] if pt else 0.0)


def _near_nodes(g, txt, exclude=None, memory=None):
    """가장 가까운 노드. 기억이 있으면 대화에서 살아 있는 쪽으로 기운다.

    가산은 *순위* 만 바꾼다. 돌려주는 점수는 순수 유사도라, 문턱(A_MIN/OK_MIN)
    판정은 활성값의 영향을 받지 않는다. 그래야 아까 무슨 이야기를 했다는
    이유로 근거 없는 답이 새어나오지 않는다."""
    v = _embed(txt)
    every = _all_scores(g, v)
    if every is None:
        best, score, rank = None, 0.0, -1.0
        for n in g["노드"]:
            if n == exclude:
                continue
            c = float((g["vec"][n] @ v).max())
            r = c + (memory.bonus(n) if memory else 0.0)
            if r > rank:
                best, score, rank = n, c, r
        return best, score
    names = g["_이름들"]
    if memory is None and exclude is None:      # 흔한 길. 파이썬 루프가 아예 없다
        i = int(every.argmax())
        return names[i], float(every[i])
    best, score, rank = None, 0.0, -1.0
    for c, n in zip(every, names):
        if n == exclude:
            continue
        c = float(c)
        r = c + (memory.bonus(n) if memory else 0.0)
        if r > rank:
            best, score, rank = n, c, r
    return best, score


def _pick_topic(question, names):
    """질문에 노드 이름이 여럿 걸렸을 때 무엇이 주제인가.

    1) 조각을 버린다. '저작권 침해' 의 '저작' 은 '저작권' 의 일부다.
    2) 긴 것이 이긴다. 더 구체적이기 때문이다 — '국가에 손해배상' 은
       '국가' 가 아니라 '손해배상' 이야기다.
    3) 길이가 같으면(계약/취소, 고소/취하) 먼저 나온 쪽이다. 한국어는
       주제를 앞에 둔다 — '계약 취소' 는 계약 이야기지 취소 이야기가 아니다."""
    other = [n for n in names if not any(n != m and n in m for m in names)]
    long_thing = max(len(n) for n in other)
    t = "".join(question.split())
    return min((n for n in other if len(n) == long_thing),
               key=lambda n: t.find("".join(n.split())))


def fit_particle(txt):
    """'저작권 는' -> '저작권은'. 받침에 맞추고 조사를 이름에 붙인다.

    노드 이름이 무엇일지 미리 알 수 없으니 템플릿에 조사를 박을 수 없다.
    그래서 조립할 때는 띄워 두고 여기서 앞 글자 받침을 보고 고른다.

    고른 뒤에는 붙인다. 원래는 '이름이 전문용어라 붙이면 안 읽힌다' 고 띄워
    뒀는데, 실제 출력으로 재보니 긴 이름도 붙인 쪽이 낫다 —
    '부당해고등의구제신청 은' 이 '부당해고등의구제신청은' 보다 읽기 좋지 않다.
    한국어에서 조사를 띄우면 그것만으로 기계가 쓴 티가 난다."""
    pos, attached = dialect.get("_조사자리"), dialect.get("_띄운조사")
    if pos:
        # 종성 차례. 0번은 받침 없음이라 자리를 비운다 — 한 칸이라도 밀리면
        # ㄹ 을 ㄷ 으로 읽어 예외가 통째로 안 걸린다.
        import hangul
        exception = dialect.get("조사예외") or {}
        def fixes(m):
            front, particle = m.group(1), m.group(2)
            batchim_text = hangul.batchim(front) or ""
            batchim = bool(batchim_text)
            picked = dialect["조사짝"][particle][0 if batchim else 1]
            # 받침이 있어도 예외인 것이 있다. ㄹ 받침은 '으로' 가 아니라 '로' 다
            # (서울로·물로·자율로). 이 예외가 없으면 '서울으로' 가 나온다.
            e = exception.get(picked)
            if e and batchim and batchim_text in e.get("받침예외", ()):
                picked = e["쓸것"]
            return front + " " + picked
        txt = pos.sub(fixes, txt)
    return attached.sub(r"\1\2", txt) if attached else txt


def _endpoint(g, txt, exclude=None):
    """경로 질문의 한쪽 끝. 이름이 그대로 있으면 그것이 우선이다.

    벡터로만 잡으면 '정당방위' 를 물었는데 '방위' 가 끝점이 된다 —
    개념망이 상위어에 하위어 표현을 붙여 놓기 때문이다."""
    name = _name_as_is(g, txt, exclude=exclude)
    if name:
        n = _pick_topic(txt, name)
        return n, float((g["vec"][n] @ _embed(txt)).max())
    return _near_nodes(g, txt, exclude)


def _co_occurs(g, a, b):
    """이어지지는 않아도 같은 대목에 함께 나올 수 있다. 그것도 사실이다."""
    place = lambda n: set((g["메타"].get(n) or {}).get("출처") or [])
    together = sorted(place(a) & place(b))
    return together[0] if together else None


def _find_excerpt(g, question, min_n=None):
    """발췌를 노드를 거치지 않고 바로 찾는다. -> (문장, 곳, 주인노드, 점수)

    지금까지는 질문 -> 노드 -> 그 노드의 발췌 순서였다. 그러면 노드를 틀리는
    순간 발췌도 틀린다. 그런데 법 코퍼스는 조문 하나에 노드가 중앙값 12개라
    노드 고르기가 병목이다 — 주제 적중이 2% 였다.

    발췌를 바로 찾으면 그 병목을 건너뛴다. 같은 시험에서 노드 경유가 1~3%,
    직접 검색이 17%(상위 5 안이면 40%)였다. 열 배다.

    문턱은 그래프의 OK_MIN 을 쓴다. 매직 넘버를 두면 안 된다 — 처음 0.45 로
    했더니 'asdf qwer zxcv'(0.567)와 '내일 날씨 어때'(0.368)가 답을 받았다.
    근거 없이 답하지 않는다는 것이 이 엔진의 전부라 그건 회귀다. 재보니
    무관한 질문은 0.57 이하, 답해야 할 질문은 0.64 이상으로 깨끗이 갈렸다.
    OK_MIN(0.60)이 그 사이에 있고, --tune 이 그래프마다 보정해 준다.

    색인은 처음 물을 때 한 번 만들고 그래프에 붙여 둔다."""
    import numpy as np
    if min_n is None:
        min_n = g["임계값"]["OK_MIN"]
    table = g.get("_발췌색인")
    if table is None:
        sentence, place, holder = [], {}, {}
        for n, m in g["메타"].items():
            for x in m.get("발췌", ()):
                t = (x.get("글") or "").strip()
                if len(t) > 10 and t not in holder:
                    sentence.append(t)
                    place[t] = x.get("곳", "")
                    holder[t] = n
        if not sentence:
            g["_발췌색인"] = (None, [], {}, {})
            return None
        # 발췌고르기 와 같은 이유로 발췌가 속이다.
        P = []
        for i in range(0, len(sentence), 256):
            P.append(_embed_sub_all([mask_numbers(t) for t in sentence[i:i + 256]]))
        table = (np.vstack(P), sentence, place, holder)
        g["_발췌색인"] = table
    P, sentence, place, holder = table
    if P is None:
        return None
    pt = P @ _embed(question)
    i = int(pt.argmax())
    if float(pt[i]) < min_n:
        return None
    return sentence[i], place[sentence[i]], holder[sentence[i]], float(pt[i])


class DialogueMemory:
    """대화 전체를 그래프 위의 활성값으로 들고 있다.

    창을 N턴으로 자르면 N+1턴 전 이야기가 통째로 사라진다. 사람은 그렇게
    기억하지 않는다 — 오래된 것은 옅어지지 뚝 끊기지 않는다. 그래서 창 대신
    감쇠를 쓴다. 대화에 나온 노드는 활성값을 얻고 턴마다 조금씩 식는다.
    한 번 나온 것은 영원히 0 이 되지 않으므로 대화 전체가 남는다.

    쓰는 곳은 하나다: 후보가 엇비슷할 때 아까 이야기하던 쪽으로 기운다.
    없던 것을 만들어내지는 않는다 — 활성값은 순위를 바꿀 뿐 문턱을 낮추지
    않는다. 그래야 근거 없는 답이 활성값 때문에 새어나오지 않는다."""

    def __init__(self, decay=0.75, weight=0.15, min_n=0.02):
        self.value = {}
        self.decay, self.weight, self.min_n = decay, weight, min_n
        self.turn = 0
        self.flow = []          # 무엇을 물었고 무엇으로 답했는지
        # 같은 오타는 계속 난다. 키보드 배열도 버릇도 그대로이기 때문이다.
        # 한 번 되묻고 확인되면 다음부터는 묻지 않는다.
        self.typo = {}

    def record_turn(self, nodes, question=None, topic=None):
        self.turn += 1
        for k in list(self.value):
            self.value[k] *= self.decay
            if self.value[k] < self.min_n:
                del self.value[k]
        for n in nodes:
            if n:
                self.value[n] = min(1.0, self.value.get(n, 0.0) + 1.0)
        if question is not None:
            self.flow.append((question, topic))

    def bonus(self, node):
        """이 노드가 대화에서 얼마나 살아 있나. 0 이면 처음 나오는 것이다."""
        return self.weight * self.value.get(node, 0.0)

    def hottest(self, count=5):
        return sorted(self.value, key=lambda n: -self.value[n])[:count]

    def save(self, path, src=None):
        """대화를 파일로. 활성값 뭉치는 원본 그래프 위의 부분그래프 선택이라,
        어느 그래프의 어느 노드가 얼마나 살아 있는지만 적으면 그대로 복원된다.

        그래서 대화가 옮겨 다닌다 — 저장하고 이어서 하거나, 남에게 건네
        같은 맥락에서 계속하게 할 수 있다. 원본 그래프는 안 건드린다."""
        json.dump({"출처": src, "턴": self.turn,
                   "감쇠": self.decay, "무게": self.weight, "최소": self.min_n,
                   "활성": self.value, "흐름": self.flow, "오타": self.typo},
                  open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        return path

    @classmethod
    def read(cls, path):
        d = json.load(open(_abs(path), encoding="utf-8"))
        mem = cls(d.get("감쇠", 0.75), d.get("무게", 0.15), d.get("최소", 0.02))
        mem.value = dict(d.get("활성", {}))
        mem.turn = d.get("턴", 0)
        mem.flow = [tuple(x) for x in d.get("흐름", [])]
        mem.typo = dict(d.get("오타", {}))
        mem.src = d.get("출처")
        return mem

    def typo_memory(self, wrong_words, fixed_phrase):
        self.typo[wrong_words] = fixed_phrase

    def resolve_typo(self, question):
        """이미 확인된 오타는 조용히 고친다. 두 번 묻지 않는다."""
        for template, bar in self.typo.items():
            if template in question:
                question = question.replace(template, bar)
        return question


# 주어를 생략한 후속 질문. NPC 대화는 이 모양으로 흘러간다.
_title_line = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_numbered_line = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
_bullet_line = re.compile(r"^\s*[-*]\s+(.+)$")
_code_fence = re.compile(r"^\s*```")


def read_procedure(paths):
    """문서에서 순서 있는 대목을 뽑는다. -> [{제목, 단계[], 출처, 결}]

    절차는 관계로 흩어 놓으면 순서를 잃는다. '판정 밴드를 추가하려면' 의 답은
    'judge 를 고치고, 대사 키를 넣고, 검사를 더한다' 인데, 각각을 따로 아는
    것과 순서를 아는 것은 다르다.

    그래서 원문의 순서를 그대로 들고 온다. 번호 목록·불릿·bash 블록은 이미
    순서가 있는 글이고, 쪼개지 않고 통째로 보관하면 지어낼 여지가 없으면서
    순서가 살아 있다.

    이어지는 줄은 앞 항목에 붙인다. 마크다운은 한 항목을 여러 줄에 걸쳐
    쓰는 일이 흔해서, 안 붙이면 '회귀 문항이 1개 늘고,' 처럼 문장이 잘린다.

    제목은 상위 제목까지 함께 들고 있는다('개발 > 8. 기여하기 좋은 곳').
    절 제목만으로는 무엇에 대한 절차인지 모를 때가 많다."""
    group = []
    for p in (paths if isinstance(paths, (list, tuple)) else [paths]):
        p = _abs(p)
        target = ([os.path.join(p, f) for f in sorted(os.listdir(p))
                 if f.endswith(".md")] if os.path.isdir(p) else [p])
        for f in target:
            name = os.path.splitext(os.path.basename(f))[0]
            upper = {}                      # 깊이 -> 제목
            title, depth, step, code_inside = None, 0, [], False
            table_line, alive_stmt = set(), []
            def join():
                if title and len(step) >= 2:
                    loc = [upper[d] for d in sorted(upper) if d < depth] + [title]
                    group.append({"제목": " > ".join([name] + loc[-2:]),
                                 "단계": list(step), "출처": name,
                                 # 표는 절차가 아니라 조회다. 순서가 뜻이 없고
                                 # 묻는 사람이 원하는 것은 맞는 한 줄이다.
                                 "표": len(table_line) > len(step) // 2,
                                 # 매칭은 절 전체로, 답은 단계로. 'PR 전에 위
                                 # 넷이 통과해야' 는 산문에 있어서, 산문을
                                 # 안 보면 'PR 전에' 라는 물음이 못 찾는다.
                                 "본문": " ".join(alive_stmt)[:600]})
            for line in open(f, encoding="utf-8").read().split(chr(10)):
                if _code_fence.match(line):
                    code_inside = not code_inside
                    continue
                m = _title_line.match(line)
                if m and not code_inside:
                    join()
                    depth = len(m.group(1))
                    for d in [k for k in upper if k >= depth]:
                        upper.pop(d)
                    title, step, table_line, alive_stmt = m.group(2).strip(), [], set(), []
                    upper[depth] = title
                    continue
                if code_inside:
                    t = line.strip()
                    if t and not t.startswith("#"):
                        step.append(t)
                    continue
                m = _numbered_line.match(line) or _bullet_line.match(line)
                if m:
                    t = m.group(m.lastindex).strip()
                    if len(t) > 4:
                        step.append(t)
                elif line.strip().startswith("|") and line.count("|") >= 3:
                    # 표도 절차다. 이 저장소 문서는 '무엇을 하려면 어디를
                    # 본다' 를 표로 적는다 — 표를 버리면 그 답이 통째로 없다.
                    slot = [c.strip() for c in line.strip().strip("|").split("|")]
                    if slot and not all(set(c) <= set("-: ") for c in slot):
                        t = " — ".join(c for c in slot if c)
                        if len(t) > 4:
                            step.append(t)
                            table_line.add(len(step) - 1)
                elif step and line.startswith(("  ", "\t")) and line.strip():
                    step[-1] = step[-1].rstrip() + " " + line.strip()
                elif line.strip():
                    alive_stmt.append(line.strip())
            join()
    return group


def find_procedure(group, question, min_n=0.35, count=1):
    """질문에 맞는 절차. 뜻과 글자를 함께 본다.

    뜻(임베딩)만 보면 'PR 전에 뭘 해야 해' 가 '불변식' 절로 샜다. 절차를
    묻는 말에는 'PR'·'판정 밴드' 처럼 그대로 적힌 낱말이 들어 있는 일이
    많아, 글자가 겹치는지를 함께 봐야 한다.

    여기가 이 기능에서 가장 약한 자리다. 라벨 기준 3/7 이고, 노드 고르기에서
    쓴 숙고(후보 다섯을 각각 밀어보기)를 그대로 옮겨봤지만 안 통했다 —
    단계 점수를 섞는 비율을 0/30/50% 로, 명령이 든 절을 밀어주는 가산을
    0/0.03 으로, 표에 벌점을 0/0.05 로 돌려봤는데 어느 조합도 3/7 을 못
    넘었다(1~3/7). 숙고가 노드에서는 3% -> 6% 를 회수했는데 절에서는 아니다.

    노드는 '이 노드의 발췌가 질문에 답하나' 라는 검증 신호가 있었다. 절에는
    그만한 신호를 아직 못 찾았다. 다음에 볼 것은 질문의 종류(무엇/어떻게/
    어디)를 먼저 가르고 종류별로 다른 절을 보는 쪽이다."""
    if not group:
        return None
    v = _embed(question)
    word = [w for w in re.findall(r"[가-힣A-Za-z]{2,}", question)
            if not any(t in w or w in t for t in (dialect.get("질문틀") or []))]
    # 자료에 아예 없는 말이 남으면 딴 얘기다 — 그래프 쪽 _모르는말 과 같은
    # 수법이다. 이 문이 없으면 '코틀린 퀵정렬' 에 러스트 코드를 내준다.
    # 다국어 코드 자료로 재보니 없는 조합 5개를 5개 다 지어냈다.
    sea = group[0].get("_바다")
    if sea is None:
        sea = " ".join(x["제목"] + " " + x.get("본문", "") + " "
                        + " ".join(x["단계"]) for x in group)
        group[0]["_바다"] = sea
    ending = dialect.get("어미") or []
    stripped_particle = dialect.get("떼는조사") or []

    def knows(w, txt):
        if any(w.endswith(e) for e in ending):
            return True     # 서술어는 딴 얘기의 증거가 못 된다
        # 조사만 뗀다. 아무 데서나 자르면 '자바스크립트로' 가 '자바' 로
        # 걸려서 자바 코드를 내주고, 두 글자에서 멈추면 'C로' 가 안 걸린다.
        # 띄어쓰기는 뜻이 아니다 — 자료의 '이진 검색' 과 물음의 '이진검색'
        # 은 같은 말이다. 뗀 채로 견준다.
        attach = txt.replace(" ", "")
        if w in attach:
            return True
        return any(w.endswith(j) and w[:-len(j)] in attach for j in stripped_particle)
    if not all(knows(w, sea) for w in word):
        return None if count == 1 else []

    score = []
    for x in group:
        step_text = " ".join(x["단계"])[:400]
        alive_stmt_text = x.get("본문", "")[:400]
        # 제목이 가장 세고 산문이 가장 약하다. 제목이 '무엇을 하는 대목인가'
        # 이고 산문은 곁가지라, 산문을 같은 무게로 보면 엉뚱한 절로 샌다.
        # 여기도 답이 될 쪽이 속이다. 뒤집어 보니 긴 절이 이겼다 —
        # '개발 흐름이 어떻게 되나' 가 '6. 개발 흐름' 대신 더 긴
        # 'README > 그래프 성장 도구' 로 샜다. 제목이 짧아서 실제로 무게를
        # 지는 것은 제목 항이고, 단계글·산문글은 400자라 거의 0 이 된다.
        meaning = max(float(_embed_sub(x["제목"]) @ v),
                 0.9 * float(_embed_sub(step_text) @ v) if step_text else 0.0,
                 0.5 * float(_embed_sub(alive_stmt_text) @ v) if alive_stmt_text else 0.0)
        body = x["제목"] + " " + step_text + " " + alive_stmt_text
        overlap = (sum(1 for w in word if w in body) / len(word)) if word else 0.0
        score.append((meaning + 0.25 * overlap, x))   # 글자가 겹치면 조금 밀어준다
    score.sort(key=lambda p: -p[0])
    # 자료에는 있는데 고른 절에는 없고 다른 절 제목에 있는 말 — 묻는 사람은
    # 그 다른 절을 물었고 거기에 답이 없다. '러스트로 BFS' 가 그렇다.
    title_sea = " ".join(y["제목"] for y in group)

    def mismatch(x):
        txt = x["제목"] + " " + x.get("본문", "") + " " + " ".join(x["단계"])
        other = [w for w in word
             if not any(w.endswith(e) for e in ending) and not knows(w, txt)]
        return any(knows(w, title_sea) for w in other)
    pick = [x for c, x in score[:count] if c >= min_n and not mismatch(x)]
    if count == 1:
        return pick[0] if pick else None
    return pick


def procedure_answer(x, scale=1, question=None):
    """원문 그대로 낸다. 지어낸 것이 없다.

    절차는 순서가 뜻이므로 차례대로 낸다. 표는 순서가 뜻이 없고 묻는 사람이
    원하는 것은 맞는 한 줄이라, 가장 가까운 줄을 앞세우고 나머지를 곁들인다."""
    line = ["%s" % x["제목"]]
    end = 6 * scale
    step = x["단계"]
    if x.get("표") and question:
        v = _embed(question)
        order = sorted(range(len(step)),
                      key=lambda i: -float(_embed_sub(step[i]) @ v))
        picks = [step[i] for i in order[:end]]
        line.append("  → " + picks[0])
        for t in picks[1:3 * scale]:
            line.append("    (곁: %s)" % t)
        return chr(10).join(line)
    for i, t in enumerate(step[:end], 1):
        line.append("  %d. %s" % (i, t))
    if len(step) > end:
        line.append("  … 그 밖에 %d단계 더 (자세히 라고 하면 더 본다)"
                  % (len(step) - end))
    return chr(10).join(line)


_code_name = re.compile(r"`([A-Za-z_가-힣][A-Za-z0-9_가-힣]*)\(?\)?`"
                      r"|\b([a-z_][a-z0-9_]{3,})\(\)")


def _find_code(code_g, name):
    """코드 그래프에서 이름에 맞는 노드. 함수명은 표기가 흔들린다."""
    cand = [name, name.rstrip("()"), name + "()"]
    for n in code_g["노드"]:
        label = code_g["메타"].get(n, {}).get("label") or n
        if label in cand or n in cand or n.split("_")[-1] in cand:
            return n
    return None


def woven_answer(question, procedure_group, code_g=None, scale=1, beside_count=2):
    """절차와 코드를 엮어 한 답으로 낸다.

    문서는 '무엇을 어떤 순서로' 를 알고, 코드 그래프는 '그것이 어디 있고
    무엇을 건드리는지' 를 안다. 둘을 따로 물으면 사람이 머리로 이어야 한다.

    엮되 지어내지 않는다. 단계는 문서 원문 그대로이고, 위치와 호출은 코드
    그래프의 엣지 그대로다. 조각마다 어디서 왔는지가 남는다."""
    cands = find_procedure(procedure_group, question, count=beside_count + 1)
    if not cands:
        return None
    x = cands[0]
    line = ["## %s" % x["제목"], ""]
    end = 6 * scale
    step = x["단계"]
    if x.get("표"):
        v = _embed(question)
        step = sorted(step, key=lambda t: -float(_embed_sub(t) @ v))[:end]
    else:
        step = step[:end]

    seen = set()
    for i, t in enumerate(step, 1):
        line.append("%d. %s" % (i, t))
        if not code_g:
            continue
        names = [a or b for a, b in _code_name.findall(t)]
        for name in names[:3 * scale]:
            if name in seen:
                continue
            seen.add(name)
            n = _find_code(code_g, name)
            if not n:
                continue
            m = code_g["메타"].get(n, {})
            pos = "%s %s" % (m.get("file", ""), m.get("loc", "")) if m.get("file") else ""
            out_edges, in_edges = _adjacent(code_g)
            call = [y for r, y in out_edges.get(n, ()) if r == "calls"][:3 * scale]
            called = [y for r, y in in_edges.get(n, ()) if r == "calls"][:2 * scale]
            chunk = ["   · `%s`" % name]
            if pos:
                chunk.append("— %s" % pos.strip())
            if call:
                chunk.append("· 부른다: %s" % ", ".join(call))
            if called:
                chunk.append("· 불린다: %s" % ", ".join(called))
            if len(chunk) > 1:
                line.append(" ".join(chunk))
    if len(x["단계"]) > end:
        line.append("")
        line.append("… 그 밖에 %d단계 더." % (len(x["단계"]) - end))
    # 어느 절이 답인지 고르는 정확도가 낮다(라벨 기준 3/7). BM25·숙고·절 유형
    # 을 다 재봤지만 아무것도 이걸 못 넘었고, 문제가 일곱 개뿐이라 더 맞추는
    # 것은 잡음을 쫓는 일이다. 그래서 순위를 감추지 않고 다음 후보를 같이
    # 내놓는다 — 확신이 없으면 되묻는다는 이 엔진의 태도 그대로다.
    beside = cands[1:]
    if beside:
        line.append("")
        line.append("이 절이 아니라면: " + " / ".join(y["제목"] for y in beside))
    return chr(10).join(line)


def dialogue_question(question, memory):
    """대화 자체에 대한 물음이면 대화 기억에서 답한다. -> 답 또는 None.

    지식 그래프는 세상에 대한 사실이고, 대화 그래프는 이 사람에 대한 사실이다.
    '아까 뭐 물어봤지' 는 세상 지식으로는 못 답하지만 대화 기록에는 적혀 있다.
    그래서 근거가 있고, 몇 번째 턴인지까지 댈 수 있다 — 영수증이 붙는다.

    잡담에 답하는 첫 걸음이다. 잡담이라고 다 근거가 없는 것은 아니다."""
    if not memory or not memory.turn:
        return None
    template = dialect.get("_대화질문")
    if not template or not template.search(question):
        return None
    # '처음' 을 먼저 본다. '처음에 뭐 물어봤어' 는 둘 다 걸리는데
    # 묻는 사람이 알고 싶은 것은 처음이다. 좁은 것이 먼저다.
    if re.search(r"처음|첫\s*(질문|말)", question):
        if not memory.flow:
            return "아직 아무것도 안 물었다."
        return "처음 물은 것은 「%s」 였다." % memory.flow[0][0]
    if re.search(r"뭐\s*물어|무엇을\s*물어|뭘\s*물어|물어봤", question):
        front = [q for q, _t in memory.flow][-3:]
        if not front:
            return "아직 아무것도 안 물었다."
        return "방금까지 %s 하고 물었다." % ", ".join("「%s」" % q for q in front)
    if re.search(r"무슨\s*(얘기|이야기|말)|어디까지|무슨\s*주제", question):
        hot = memory.hottest(4)
        if not hot:
            return "아직 이야기한 것이 없다."
        return "%d턴째이고 %s 이야기를 하고 있었다." % (memory.turn, ", ".join(hot))
    if re.search(r"오타|잘못\s*(썼|친)|틀리게", question):
        if not memory.typo:
            return "고친 오타가 없다."
        return "%s 로 고쳐 두었다." % ", ".join(
            "「%s」는 「%s」" % (a2, b2) for a2, b2 in memory.typo.items())
    return None


def _fill_context(question, memory):
    """주어가 빠진 질문에 아까 이야기하던 것을 넣는다. -> (채운 질문, 주어)

    재순위로는 안 된다. '왜 그래야 해' 는 '해고' 와 닮은 구석이 없어서
    가산을 얼마를 줘도 순위가 안 바뀐다. 주어가 아예 없으므로 넣어줘야 한다.
    engine.py 의 대명사풀기와 같은 수법이고, 다른 점은 직전 세 턴이 아니라
    대화 전체에서 가장 살아 있는 것을 쓴다는 것이다."""
    template = dialect.get("_주어없음")
    if not memory or not template or not template.search(question):
        return question, None
    hot = memory.hottest(1)
    if not hot:
        return question, None
    return "%s %s" % (hot[0], question), hot[0]


# 문장 부호 없이 이어 붙인 물음을 가르는 자리. 조각내기 는 문장 경계만 보므로
# `증거는 어디에 적고 임계값은 어떻게 정하나` 를 한 덩어리로 준다.
_link_word = re.compile(r"\s*(?:그리고|또한|동시에|한편|그리고서|또)\s+")
# 주제 조사가 두 번 나오면 두 가지를 묻는 것이다 — `A 는 …고 B 는 …`.
# 앞 대목이 연결어미(고/며/지만)로 끝날 때만 가른다. 그냥 `은/는` 마다 가르면
# `공통층은 사례층은 뭐가 달라` 같은 한 물음도 쪼개진다.
# 어미는 앞 대목에 붙여 둔다. 잘라내면 `증거는 어디에 적` 이 되어 사람에게
# 보이는 머리말이 뭉개진다.
_link_ending = re.compile(r"(?:(?<=고)|(?<=며)|(?<=지만))\s+"
                       r"(?=[가-힣A-Za-z]{2,12}(?:은|는)\s)")


def _split_passages(question):
    """물음을 의미 대목으로. 문장 경계 + 이음말 + 이음어미."""
    chopped = split_fragments(question)
    # 조각내기 는 [전체] + 문장들 을 주는데, 문장 경계가 없으면 [전체] 하나뿐이다.
    # 그때 [1:] 로 자르면 아무것도 안 남는다 — `증거는 어디에 적고 임계값은
    # 어떻게 정하나` 가 통째로 사라졌다.
    chunk = []
    for x in (chopped[1:] if len(chopped) > 1 else chopped):
        for y in _link_word.split(x):
            chunk += [z for z in _link_ending.split(y) if z]
    return [x.strip() for x in chunk if len(x.strip()) > 5]


def _multi_passage(g, question, memory=None, scale=1):
    """한 입력에 여러 개를 물었으면 각각 답한다. 아니면 None.

    사람은 한 번에 하나만 묻지 않는다. `증거는 어디에 적고 임계값은 어떻게
    정하나` 는 두 가지를 묻는 물음인데, 지금까지는 조각을 **찾는 데는** 다
    쓰고 **답할 때는 최고점 하나만** 썼다. 나머지 조각은 점수 비교에만 쓰이고
    버려졌다 — 조각을 따로 물으면 서로 다른 답이 나오는데도.

    조각내기 가 이미 나눠 놓은 것을 쓴다. 대목마다 따로 물어 서로 다른 주제가
    둘 이상 나올 때만 합친다. 하나로 모이면(`임계값이 뭐야. 그건 어떻게 정해`)
    None 을 돌려 원래 길로 보낸다 — 같은 것을 두 번 답하면 안 된다.

    문턱을 낮추지 않는다. 대목마다 물어보기 를 그대로 다시 부르므로 관문도
    그대로다. 근거 없는 답이 여기서 새면 안 된다."""
    passage = _split_passages(question)
    if len(passage) < 2:
        return None
    seen, answers = [], []
    for x in passage:
        meaning2, ans2, topic2 = ask(g, x, memory, _DONT_SPLIT=True)
        if meaning2 != "설명" or not topic2 or topic2 in seen:
            continue
        seen.append(topic2)
        answers.append((x, ans2))
    if len(answers) < 2:
        return None
    line = []
    for x, ans2 in answers:
        line.append("**%s**" % x.strip())
        line.append(ans2)
    return "설명", "\n\n".join(line), seen[0]


def ask(g, question, memory=None, _DONT_SPLIT=False):
    """문장 -> 설명. 판정이 아니라 안내다.

    graphify 는 여기서 LLM 에 서브그래프를 넘겨 답을 쓰게 한다.
    이 엔진은 그래프에 있는 것만 골라 조립한다 — 지어내지 않고 GPU 도 안 쓴다."""
    if memory:
        question = memory.resolve_typo(question)
        ans = dialogue_question(question, memory)
        if ans:
            return "대화", ans, None
    question, _filled_subject = _fill_context(question, memory)
    template_verbose = dialect.get("_자세히")
    scale = 3 if (template_verbose and template_verbose.search(question)) else 1
    meaning = intent(question)
    A_MIN, OK_MIN = g["임계값"]["A_MIN"], g["임계값"]["OK_MIN"]

    if not _DONT_SPLIT:
        many = _multi_passage(g, question, memory, scale)
        if many:
            return many

    if meaning == "경로":
        split = [x.strip() for x in re.split(r"[와과랑,]|하고", question)
                if len(x.strip()) > 1]
        if len(split) >= 2:
            a, ca = _endpoint(g, split[0])
            b, cb = _endpoint(g, split[1], exclude=a)
            if a and b and min(ca, cb) >= A_MIN:
                # 바로 이어진 것이 있으면 그것이 답이다.
                # 없으면 구조 관계(코드 그래프의 호출·참조 같은 것)로만 이어 본다.
                # '설명함' 은 한 다리만 건너면 무엇이든 잇는다 — '저작권 -> 대통령령
                # -> 음주운전' 같은 것을 관계라고 부르면 관계라는 말이 뜻을 잃는다.
                loc = (linking_path(g, a, b, max_n=1)
                      or linking_path(g, a, b, remove_relation=("같은조문", "설명함")))
                if loc:
                    return "경로", fit_particle(explain_path(g, loc)), a
                place = _co_occurs(g, a, b)
                if place:
                    return ("경로", fit_particle(
                        "%s 와 %s 는 이어지지 않지만 %s 에 함께 나온다."
                        % (a, b, _passage_name(place))), a)
                return "경로", fit_particle(
                    "%s 와 %s 는 그래프에서 이어지지 않는다." % (a, b)), a
        meaning = "이웃"

    # 두 글자 개념(해고·기각·상법)이 흔하다. 3글자 이상만 받으면
    # '해고는 언제?' 가 '해고' 를 놓치고 '해고사유' 로 샌다.
    as_is = _name_as_is(g, question)
    if as_is:
        # 이름이 여럿 걸리면 아까 이야기하던 쪽을 고른다
        topic = (max(as_is, key=lambda n: memory.bonus(n)) if memory and len(as_is) > 1
                and max(memory.bonus(n) for n in as_is) > 0
                else _pick_topic(question, as_is))
        # 이름이 들어 있다고 그 이야기인 것은 아니다. '양자역학' 안에는
        # '양자'(민법)가 들어 있다. 확신이 없으면 벡터 쪽에 넘긴다.
        if float((g["vec"][topic] @ _embed(question)).max()) >= A_MIN:
            # 이름이 그대로 있어도 나머지를 모르면 이 그래프 얘기가 아니다.
            # '주말에 영화 볼까' 는 '영화' 가 들어 있다고 저작권 조문을 답했다.
            unknown = _unknown_words(g, question, topic)
            if unknown:
                fixes = {w: fix_typo(g, w) for w in unknown}
                fixes = {w: c for w, c in fixes.items() if c}
                if fixes and len(fixes) == len(unknown):
                    changed = question
                    for w, c in fixes.items():
                        changed = changed.replace(w, c)
                        if memory:
                            memory.typo_memory(w, c)
                    return ("A", "혹시 %s 말인가?" % changed.strip(), None)
                return ("미지", "그건 이 그래프에 없는 이야기다."
                        " (%s 을(를) 모른다)" % ", ".join(unknown[:3]), None)
            return "설명", explain(g, topic, meaning, question=question, scale=scale), topic

    best, score = None, 0.0
    for chunk in split_fragments(question):
        n, c = _near_nodes(g, chunk, memory=memory)
        if c > score:
            best, score = n, c
    # 숙고: 1등을 그냥 쓰지 않고 상위 후보를 각각 밀어본다. 문턱 판정은
    # 이름 유사도(score)로 그대로 하고, 숙고는 그 안에서 누구를 고를지만
    # 바꾼다 — 근거 없는 답이 숙고 때문에 새어나오면 안 되기 때문이다.
    if best and score >= A_MIN:
        cand, _best = _cands(g, question)
        picks, _s = _deliberate(g, question, cand, memory)
        if picks:
            best = picks

    # 노드가 흐리면 발췌를 바로 찾는다. 노드 고르기가 병목이라, 노드를 못
    # 고르겠을 때 포기하는 것보다 대목을 직접 꺼내는 편이 열 배 낫다.
    if score < OK_MIN:
        direct = _find_excerpt(g, question)
        if direct and direct[3] > score:
            sentence, place, holder, _c = direct
            return "설명", fit_particle("%s%s" % (
                sentence, (" — " + _passage_name(place)) if place else "")), holder

    if score < A_MIN:
        return "미지", "그건 이 그래프에 없는 이야기다.", None
    # 노드 하나가 걸렸다고 그 이야기인 것은 아니다. 걸린 것을 빼고도
    # 그래프가 모르는 말이 남으면 이 그래프에서 다룰 질문이 아니다.
    unknown = _unknown_words(g, question, best)
    if unknown:
        # 오타일 수 있다. 자모 하나 차이로 아는 말이 되면 그걸 되묻는다.
        # 조용히 고치지 않는다 — '주말' 이 '주물' 로 고쳐지는 일이 실제로
        # 있어서, 고친 것을 사람에게 보이고 확인받는 편이 맞다.
        fixes = {w: fix_typo(g, w) for w in unknown}
        fixes = {w: c for w, c in fixes.items() if c}
        if fixes and len(fixes) == len(unknown):
            changed = question
            for w, c in fixes.items():
                changed = changed.replace(w, c)
                if memory:
                    memory.typo_memory(w, c)
            return ("A", "혹시 %s 말인가?" % changed.strip(), None)
        return ("미지", "그건 이 그래프에 없는 이야기다. (%s 을(를) 모른다)"
                % ", ".join(unknown[:3]), None)
    if score < OK_MIN:
        out_edges, in_edges = _adjacent(g)
        neighbor = sorted({y for _, y in out_edges.get(best, ())} |
                      {x for _, x in in_edges.get(best, ())})[:3]
        tail = (" %s 근처 이야기다." % ", ".join(neighbor)) if neighbor else ""
        return "A", fit_particle("혹시 %s 말인가?%s" % (best, tail)), best
    return "설명", explain(g, best, meaning, question=question, scale=scale), best


def grade_explain(g, max_n=400, question_count=3):
    """목표 없는 모드의 정답지. 사람이 라벨을 달지 않는다.

    논증 모드는 판례가 정답지였다 — 사실을 넣고 법원의 결론이 나오는지 본다.
    설명 모드에는 그런 것이 없어서 "무엇이 좋은 답인가" 를 잴 수가 없었다.
    여기서는 원문 자체를 정답지로 쓴다: 각 노드의 발췌는 그 노드를 물었을 때
    나와야 할 문장이다.

    세 가지를 따로 잰다. 난이도가 다르고 뜻이 다르다.

      이름     노드 이름을 그대로 묻는다. 문자열로 찾히므로 거의 다 맞는다.
               이게 낮으면 조회 경로가 깨진 것이다.
      가림     발췌에서 노드 이름을 지우고 묻는다. 문자열 단서가 없으니
               임베딩 매칭만으로 대목을 찾아야 한다. 이게 진짜 실력이다.
      대목     주제를 틀렸더라도 답에 그 문장이 들어 있으면 맞는 것으로 센다.
               쓰는 사람이 원하는 것은 옳은 대목이지 옳은 이름표다.

    오래도록 '가림' 이 한 자리 숫자였다(문서 12% · 법 9%). 엔진이 못해서가
    아니라 정답지가 자의적이어서였다. 짓기.py 는 한 문장을 그 안에 든 모든
    개념에 붙이므로 한 문장의 주인이 여럿이다 — 문서그래프는 평균 13.5개다.
    그중 하나만 정답으로 치면 나머지 12.5개를 고를 때마다 틀렸다고 센다.
    같은 문장을 발췌로 가진 노드를 전부 정답으로 치자 12% -> 76%,
    9% -> 60%, 요리는 50% -> 100% 가 됐다. 엔진은 그대로다.

    이 셈이 더 후한 것은 맞다. 다만 906노드 중 13.5개면 1.5% 라 거저 주는
    것은 아니고, 세 코퍼스가 100/76/60 으로 갈리니 변별력도 살아 있다.
    고친 뒤 '가림'(76) 과 '대목'(74) 이 거의 붙었다 — 둘 다 '정당한 대목에
    닿았나' 를 재게 되어서다. 예전의 12 대 74 간격이 곧 자의성의 크기였다.

    남은 함정 둘. 둘 다 '무엇과 무엇을 맞대도 되는가' 의 문제다.

    코퍼스   '주인 수 평균' 이 코퍼스마다 다르므로(요리 2.8 · 법 7.5 ·
             문서 13.5) 서로 다른 코퍼스의 '가림' 을 맞대면 안 된다.

    인코더   성격이 다른 인코더끼리도 맞대면 안 된다. 질문을 정답에서
             만들기 때문에 — 발췌에서 이름만 빼면 나머지 글자는 그대로다 —
             표면을 그대로 보는 방식이 구조적으로 이긴다. 문자 n-gram
             인코더가 법지식에서 가림 91% 를 냈는데, 뜯어보니 가린 질문과
             노드 이름의 유사도는 0.088 이고 원본 발췌와의 유사도가 0.921
             이었다. 이해가 아니라 받은 문장을 도로 알아본 것이고, 발췌
             직접 검색이 그 0.921 로 답했다. 같은 조건에서 신경망은 14%
             였는데 그것은 지식이 모자라서가 아니라 거의 같은 문장을
             알아보는 데 서툴러서다.

    쓰는 법은 하나다 — **같은 코퍼스, 같은 인코더**로 고치기 전후를 잰다.
    (encoder.py 의 '자모로 펴니 84% -> 75%' 는 문자 대 문자라 유효하다.)"""
    # 한 문장은 그 안에 든 개념 모두의 발췌가 된다. 그러니 그 문장의 주인은
    # 하나가 아니다 — '텍스트 폴더를 넣으면 지식 그래프가 되고, 그 그래프와
    # 대화한다' 는 텍스트 이야기이기도 하고 그래프 이야기이기도 하다.
    # 정답을 하나로 정해두면 나머지 주인을 골랐을 때 틀렸다고 세는데, 그건
    # 엔진이 틀린 것이 아니라 정답지가 자의적인 것이다. 같은 문장을 발췌로
    # 가진 노드는 전부 정답으로 친다.
    holder = {}
    for _n, _m in g["메타"].items():
        for _x in _m.get("발췌", ()):
            txt = re.sub(r"\s+", "", _x.get("글", ""))
            if len(txt) > 10:
                holder.setdefault(txt, set()).add(_n)

    name = masked = passage = total = prompt = 0
    owner_count = []
    wrong_ones = []
    for n in list(g["노드"])[:max_n]:
        excerpt = [x.get("글", "") for x in g["메타"].get(n, {}).get("발췌", [])]
        excerpt = [x for x in excerpt if len(x) > 10]
        if not excerpt:
            continue
        total += 1
        if ask(g, n)[2] == n:
            name += 1
        # 노드마다 질문 하나면 '이 노드를 아는가' 가 아니라 '이 한 문장에
        # 걸리는가' 를 잰다. 그 한 문장이 어쩌다 짧거나 표가 통째로 든
        # 것이면 노드는 멀쩡한데 점수가 떨어진다. 발췌가 여럿이면 여럿 다
        # 묻는다 — 문서그래프는 400노드 중 370개가 둘 이상이고 150개는
        # 다섯 이상이다. 그동안 첫 하나만 썼다.
        #
        # 질문을 지어내지 않고 있는 발췌를 쓰는 것이 요점이다. 지어내면
        # 제 어휘를 물려받아 늘 맞힌다 — '감쇠' 를 묻는 질문에 '감쇠' 를
        # 쓰니까. 발췌는 사람이 쓴 다른 문장이라 그 함정이 없다.
        for txt in excerpt[:question_count]:
            owners = holder.get(re.sub(r"\s+", "", txt), {n})
            # 정답 하나만 지우면 나머지 주인들의 이름이 문장에 그대로 남는다.
            # 주인이 36개인 문장에서 34개가 글자째 남아 있었다 — 글자로
            # 맞추는 인코더는 그중 아무거나 집으면 정답 처리를 받는다.
            # 실제로 문자 인코더가 가림 100% 를 냈다. 뜻으로 찾는지 재려면
            # 정답의 실마리를 전부 지워야 한다.
            masked_sentence = txt
            for o in sorted(owners, key=len, reverse=True):
                masked_sentence = re.sub(re.escape(o), " ", masked_sentence)
            if len(masked_sentence.strip()) < 10:      # 다 지우면 물을 것이 없다
                continue
            _intent, ans, topic = ask(g, masked_sentence)
            owner_count.append(len(owners))
            prompt += 1
            if topic in owners:
                masked += 1
            elif len(wrong_ones) < 8:
                wrong_ones.append((n, topic, masked_sentence[:44]))
            core = re.sub(r"\s+", "", txt)[:24]
            if core and core in re.sub(r"\s+", "", ans or ""):
                passage += 1
    return {"총": total, "물음": prompt, "이름": name, "가림": masked, "대목": passage,
            "틀린것": wrong_ones,
            "주인평균": (sum(owner_count) / len(owner_count)) if owner_count else 1.0}


def knowledge_image(g, center=None, max_n=45):
    """설명 그래프(graphify 등)를 Mermaid 로. 관계 종류마다 선이 다르다.

    492노드를 통째로 그리면 못 본다. 중심 노드에서 퍼져나가며 최대 개수까지만 담는다."""
    neighbor = {}
    for a, r, b in g["엣지"]:
        neighbor.setdefault(a, []).append((r, b))
        neighbor.setdefault(b, []).append((r, a))
    start = center or max(neighbor, key=lambda n: len(neighbor[n]))
    seen, q = {start}, deque([start])
    while q and len(seen) < max_n:
        n = q.popleft()
        for _, m in neighbor.get(n, []):
            if m not in seen and len(seen) < max_n:
                seen.add(m)
                q.append(m)

    line_ = {"설명함": "==>", "같은조문": "-.->", "같은대목": "-.->",
          "contains": "-->", "imports": "==>", "imports_from": "==>",
          "calls": "-->", "references": "-.->", "conceptually_related_to": "-.->",
          "semantically_similar_to": "-.->", "extends": "==>", "cites": "-.->"}
    nick, L = {}, ["flowchart LR"]
    def id(n):
        if n not in nick:
            nick[n] = "k%d" % len(nick)
        return nick[n]
    cluster = {}
    for n in sorted(seen):
        cluster.setdefault((g["메타"].get(n) or {}).get("community") or "기타", []).append(n)
    for name, elems in cluster.items():
        L.append('  subgraph s%d["%s"]' % (abs(hash(name)) % 9999, name))
        for n in elems:
            L.append('    %s["%s"]' % (id(n), n.replace('"', "")))
        L.append("  end")
    # 32만 엣지짜리 그래프는 부분만 떠도 빽빽하다. 노드마다 몇 개씩만 남긴다.
    emitted, count = set(), {}
    for a, r, b in g["엣지"]:
        if a not in seen or b not in seen or (a, r, b) in emitted:
            continue
        if count.get(a, 0) >= 4 or count.get(b, 0) >= 4:
            continue
        emitted.add((a, r, b))
        count[a] = count.get(a, 0) + 1
        count[b] = count.get(b, 0) + 1
        L.append("  %s %s|%s| %s" % (id(a), line_.get(r, "---"), r, id(b)))
    L.append("  classDef 중심 fill:#1d4ed8,stroke:#1e3a8a,color:#fff")
    L.append("  class %s 중심" % id(start))
    return "\n".join(L)


def _selfcheck():
    # 설명 채점: 목표 없는 모드의 정답지. 원문 자체를 정답으로 쓴다.
    # 이름으로 물으면 거의 다 맞고(조회 경로), 이름을 지우면 크게 떨어진다
    # (임베딩 매칭만의 실력). 그 격차가 이 모드에서 개선할 자리다.
    # 벡터 캐시가 결과를 바꾸지 않는다. 두 번 열어 같은 벡터가 나와야 한다.
    _cook_p = _abs("data/예시_요리/지식그래프.json")
    if os.path.exists(_cook_p):
        import numpy as np
        _a, _b = open_(_cook_p), open_(_cook_p)
        _n = list(_a["vec"])[0]
        assert np.allclose(_a["vec"][_n], _b["vec"][_n]), "캐시가 벡터를 바꾼다"

    cook = _abs("data/예시_요리/지식그래프.json")
    if os.path.exists(cook):
        _r = grade_explain(open_(cook))
        assert _r["총"] >= 5, _r
        assert _r["이름"] == _r["총"], _r          # 조회 경로는 다 맞아야 한다
        # '이름' 은 노드마다 한 번이고 '가림/대목' 은 발췌마다 한 번이라
        # 분모가 다르다. 개수가 아니라 비율로 본다.
        assert _r["물음"] >= _r["총"], _r
        # 이름을 지우면 문자열 단서가 없어지니 더 어렵거나 같다. 노드 8개짜리
        # 장난감에서는 같아진다 — 한 문장의 주인이 2.8개뿐이라 아무나 맞으면 된다.
        assert (_r["가림"] / _r["물음"]) <= (_r["이름"] / _r["총"]) + 1e-9, _r
        # '대목' 과 '가림' 은 서로 포함관계가 아니다. 가림은 그 문장의 주인
        # 아무나 맞으면 되고(관대), 대목은 그 발췌가 답에 들어 있어야 한다
        # (엄격). 문서그래프에서 가림 73 · 대목 71 로 뒤집힌다.
        assert _r["대목"] <= _r["물음"] and _r["가림"] <= _r["물음"], _r
        # 발췌 직접 검색이 붙어도 근거 없는 질문은 여전히 거절해야 한다.
        # 문턱을 0.45 로 뒀을 때 'asdf qwer zxcv'(0.567)가 답을 받았다.
        # 근거 없이 답하지 않는다는 것이 이 엔진의 전부라 그건 회귀다.
        cook_g = open_(cook)
        for _s_misc in ("asdf qwer zxcv 1234", "피카츄가 뭐야", "주식 시장 전망"):
            assert ask(cook_g, _s_misc)[0] in ("미지", "A"), (_s_misc, ask(cook_g, _s_misc))
        # 그래프에 있는 것은 대목이 그대로 나온다
        assert "두부" in (ask(cook_g, "두부는 언제 넣어요")[1] or "")

        # 대화 맥락은 창이 아니라 감쇠다. 대화 전체가 남되 오래된 것이 옅어진다.
        mem = DialogueMemory()
        for _head_ in ("두부는 언제 넣어요", "김치찌개 재료", "멸치육수는 왜 써요"):
            _t = ask(cook_g, _head_, mem)[2]
            mem.record_turn([_t], _head_, _t)
        assert len(mem.value) >= 2, mem.value                    # 세 턴이 다 남는다
        assert mem.turn == 3, mem.turn
        # 주어 없는 질문은 재순위로 안 된다. '왜 그래야 해' 는 어떤 노드와도
        # 안 닮아서 가산을 얼마 줘도 순위가 안 바뀐다. 주어를 넣어줘야 한다.
        _filled, _subject = _fill_context("왜 그래야 해", mem)
        assert _subject and _subject in _filled, (_filled, _subject)
        assert _fill_context("두부가 뭐야", mem)[1] is None      # 주어가 있으면 안 건드린다
        assert _fill_context("왜 그래야 해", DialogueMemory())[1] is None  # 빈 기억이면 못 채운다
        # 맥락이 있어도 근거 없는 질문은 거절한다. 활성값은 순위만 바꾸고
        # 문턱은 못 낮춘다 — 아까 무슨 이야기를 했다는 이유로 답이 새면 안 된다.
        for _s_misc in ("피카츄가 뭐야", "주식 시장 전망"):
            assert ask(cook_g, _s_misc, mem)[0] == "미지", (_s_misc, ask(cook_g, _s_misc, mem))
        # 대화는 파일로 옮겨 다닌다. 활성값 뭉치가 원본 그래프 위의 부분그래프
        # 선택이라, 어느 노드가 얼마나 살아 있는지만 적으면 그대로 복원된다.
        _dialogue = "_대화시험.json"
        mem.save(_dialogue, "data/예시_요리/지식그래프.json")
        _again = DialogueMemory.read(_dialogue)
        assert _again.value == mem.value and _again.turn == mem.turn, (_again.value, mem.value)
        assert _again.hottest(1) == mem.hottest(1)
        assert _again.src == "data/예시_요리/지식그래프.json"
        # 이어받은 기억으로 주어 없는 질문이 풀린다
        assert _fill_context("왜 그래야 해", _again)[1] == mem.hottest(1)[0]
        os.remove(_dialogue)

        # 숙고: 1등을 그냥 쓰지 않고 상위 후보를 각각 밀어본다.
        # 정답이 1등이 아니라 5등 안에 있는 경우가 많다 (1등 3% / 상위 5 안 7%).
        _cand, _best = _cands(cook_g, "두부는 언제 넣어요")
        assert len(_cand) >= 3 and _best > 0, (_cand, _best)
        assert _deliberate(cook_g, "두부는 언제 넣어요", _cand)[0] in _cand
        # 숙고는 누구를 고를지만 바꾸고 문턱은 못 낮춘다. 근거 없는 답이
        # 숙고 때문에 새어나오면 안 된다.
        for _s_misc in ("피카츄가 뭐야", "주식 시장 전망"):
            assert ask(cook_g, _s_misc)[0] == "미지", (_s_misc, ask(cook_g, _s_misc))

        # 단어가 들어 있다고 그 이야기인 것은 아니다. 걸린 노드를 빼고도
        # 그래프가 모르는 말이 남으면 거절한다 — 짧은 말일 때만.
        assert _unknown_words(cook_g, "주말에 두부 먹을까", "두부") == []  # 작은 그래프는 안 건다
        # 단어가 들어 있다고 그 이야기인 것은 아니다.
        law_g = open_("data/법지식/지식그래프.json")
        # 잡담에는 답하지 않는다. 모른다고 하거나 되묻는다 — 오타 교정이
        # 붙은 뒤로 '주말' 이 '주물' 로 고쳐져 되묻는 경우가 생겼는데,
        # 답을 안 한다는 점은 같다. 불변식은 '설명하지 않는다' 이다.
        for _misc2 in ("주말에 영화 볼까", "고양이 키우고 싶다", "피카츄가 뭐야"):
            assert ask(law_g, _misc2)[0] in ("미지", "A"), (_misc2, ask(law_g, _misc2))
        # 서술어는 딴 얘기의 증거가 못 된다. 구어체 어미는 격식 문서에 안 나온다.
        assert ask(law_g, "계약 취소하고 싶은데")[0] == "설명"
        assert ask(law_g, "저작권 침해 형량이 어떻게 돼")[0] == "설명"
        # 긴 글은 모르는 말이 섞여도 정상이다. 안 두면 채점이 56% -> 12% 로 무너진다.
        _long = ("제310조 전세권자가 목적물을 개량하기 위하여 지출한 금액 기타 "
               "유익비에 관하여는 소유자의 선택에 좇아 상환을 청구할 수 있다")
        assert _unknown_words(law_g, _long, "전세권") == [], _unknown_words(law_g, _long, "전세권")

        # 오타는 자모 하나 차이다. 글자로 보면 안 보이고 자모로 보면 보인다.
        assert _jamo_dist("해고", "해구") == 1
        assert _jamo_dist("해고", "고양이") > 2        # 딴 말은 멀다
        for _right, _bar_ in (("해구가", "해고"), ("짐해", "침해"), ("처발", "처벌"),
                         ("채포", "체포"), ("구재신청", "구제신청")):
            assert fix_typo(law_g, _right) == _bar_, (_right, fix_typo(law_g, _right))
        assert fix_typo(law_g, "해고") is None          # 아는 말은 안 고친다
        # 조용히 고치지 않고 되묻는다. '주말' 이 '주물' 로 고쳐지는 일이 있어서,
        # 고친 것을 보이고 확인받는 편이 맞다.
        assert ask(law_g, "현행범 채포")[0] == "A"
        assert "체포" in ask(law_g, "현행범 채포")[1]
        # 같은 오타는 계속 난다. 한 번 되묻고 나면 다음부터는 안 묻는다.
        _mem = DialogueMemory()
        assert ask(law_g, "현행범 채포", _mem)[0] == "A"
        assert _mem.typo.get("채포") == "체포", _mem.typo
        assert ask(law_g, "현행범 채포 요건", _mem)[0] == "설명"
        # 대화를 저장하면 오타도 같이 간다
        _p = "_오타시험.json"
        _mem.save(_p, "법지식")
        assert DialogueMemory.read(_p).typo == _mem.typo
        os.remove(_p)

        # 대화 자체가 답의 근거가 된다. 지식 그래프는 세상에 대한 사실이고
        # 대화 그래프는 이 사람에 대한 사실이다. 둘 다 근거가 있다.
        _mem2 = DialogueMemory()
        for _q2 in ("해고가 뭐야", "부당해고 구제신청"):
            _t2 = ask(law_g, _q2, _mem2)[2]
            _mem2.record_turn([_t2], _q2, _t2)
        assert ask(law_g, "아까 뭐 물어봤지", _mem2)[0] == "대화"
        assert "해고가 뭐야" in ask(law_g, "처음에 뭐 물어봤어", _mem2)[1]
        assert "2턴" in ask(law_g, "무슨 얘기 하고 있었지", _mem2)[1]
        # 대화 기억이 없으면 대화 질문도 없다 — 없는 것을 지어내지 않는다
        assert dialogue_question("아까 뭐 물어봤지", None) is None
        assert dialogue_question("아까 뭐 물어봤지", DialogueMemory()) is None

        # 자기 코드 그래프. 관계가 calls/contains/rationale_for 라 말투 표에 있다.
        _co = _abs("graphify-out/graph.json")
        if os.path.exists(_co):
            _cg = open_(_co)
            _short = ask(_cg, "judge 가 뭐야")[1] or ""
            _length = ask(_cg, "judge 가 뭐야 자세히")[1] or ""
            assert "engine.py" in _short, _short          # 파일과 줄을 댄다
            assert len(_length) > len(_short) * 1.5, (len(_short), len(_length))
            # 길게 답한다고 없던 것을 만들지 않는다. 늘어난 것은 전부 실제 엣지다.
            assert "호출한다" in _length
            assert ask(_cg, "judge 랑 match 무슨 관계야")[0] == "경로"

        # 코드 그래프와 문서 그래프는 서로 다른 것을 안다. 코드에는 호출
        # 구조가 있고 절차가 없다 — '새 밴드를 추가하려면' 의 답은 문서에 있다.
        _stmt = _abs("문서그래프.json")
        if os.path.exists(_stmt):
            _dg = open_(_stmt)
            assert ask(_dg, "kg읽기 랑 load 차이")[0] == "설명"
            assert ask(_dg, "새 도메인 그래프를 만들려면")[0] == "설명"
            # 문서 그래프는 호출 구조를 모른다. 겹치지 않는 것은 이름이
            # 아니라 구조다 — 문서도 `judge` 를 말하지만 그것이 무엇을
            # 부르는지는 코드 그래프에만 있다. 예전에는 '뭘 호출해' 에
            # 답하지 않는 것으로 이걸 검사했는데, 그건 모르는 말 문이
            # `judge` 를 잘못 걸러준 덕이었다. 문서가 함수 시그니처를
            # 적으면 `judge` 는 아는 말이 되고 문은 열리는 게 맞다.
            # 사실 자체를 검사한다.
            assert not any(r == "calls" for _, r, _ in _dg["엣지"])

        # 절차: 순서가 뜻이다. 원문의 순서를 그대로 들고 온다.
        if os.path.exists(_abs("docs/ko/development.md")):
            _procedures = read_procedure(["docs/ko/development.md", "README.md"])
            assert len(_procedures) >= 10, len(_procedures)
            _x = find_procedure(_procedures, "PR 전에 뭘 해야 해")
            assert _x and "개발 흐름" in _x["제목"], _x and _x["제목"]
            _ans = procedure_answer(_x, question="PR 전에 뭘 해야 해")
            # 순서가 살아 있다. --check 가 --regress 보다 먼저 나와야 한다.
            assert _ans.index("--check") < _ans.index("--regress"), _ans
            # 단계는 원문 그대로다. 지어낸 것이 없다.
            assert all(t in open(_abs("docs/ko/development.md"), encoding="utf-8").read()
                       for t in _x["단계"][:3]), _x["단계"][:3]
            # 표는 절차가 아니라 조회다. 맞는 줄이 앞에 온다.
            _t = find_procedure(_procedures, "인코더를 바꾸려면")
            if _t and _t.get("표"):
                assert "인코더" in procedure_answer(_t, question="인코더를 바꾸려면").split(chr(10))[1]

            # 절차와 코드를 엮는다. 문서는 '무엇을 어떤 순서로' 를 알고
            # 코드 그래프는 '그것이 어디 있고 무엇을 건드리는지' 를 안다.
            if os.path.exists(_abs("graphify-out/graph.json")):
                _cg2 = open_("graphify-out/graph.json")
                # 어느 절이 잡히느냐는 인코더마다 다르다. 예전엔 '매칭 방식을
                # 바꾸려면' 으로 물었는데 문자 인코더에서는 아무것도 안 잡혀
                # 이 시험이 통째로 죽어 있었다. 검색 품질이 아니라 **엮는
                # 구조**를 재야 한다. 제목으로 물으면 두 인코더 다 27/27 로
                # 제자리라, 코드가 실제로 붙는 절을 골라 그것으로 묻는다.
                _pick = None
                for _x2 in _procedures:
                    _name = [a or b for _t2 in _x2["단계"]
                             for a, b in _code_name.findall(_t2)]
                    if any(_find_code(_cg2, n) for n in _name):
                        _pick = _x2
                        break
                assert _pick, "코드 이름이 붙은 절이 하나도 없다"
                _weave = woven_answer(_pick["제목"], _procedures, _cg2, scale=3)
                assert _weave, "엮은 답이 없다"
                # 단계는 문서 원문 그대로다. 지어낸 줄이 없다.
                for _line2 in _weave.split(chr(10)):
                    _m2 = re.match(r"^\d+\. (.+)$", _line2)
                    if _m2:
                        assert _m2.group(1) in _pick["단계"], _m2.group(1)[:80]
                # 코드 위치가 붙고, 붙은 이름은 코드 그래프에 실제로 있다.
                _code_line = [y for y in _weave.split(chr(10)) if y.startswith("   · `")]
                assert _code_line, _weave[:200]
                for _line2 in _code_line:
                    _name2 = _line2.split("`")[1]
                    assert _find_code(_cg2, _name2), _name2
                assert any(("부른다" in y or "불린다" in y) for y in _code_line), _code_line[:3]
                # 코드 그래프가 없어도 절차만으로 답한다
                assert woven_answer(_pick["제목"], _procedures, None)
                # 어느 절인지 고르는 정확도가 낮아(3/7) 다음 후보를 같이 낸다.
                # 확신이 없으면 되묻는다는 태도 그대로다. 이건 **애매한**
                # 물음에서 재야 한다 — 위처럼 제목을 그대로 물으면 한 절만
                # 문턱을 넘어 곁 후보가 없는 것이 옳다.
                # 물음은 두 인코더 다 여럿을 무는 것으로 쓴다. '판정 밴드를
                # 추가하려면' 은 신경에서는 둘을 무는데 문자에서는 0개라,
                # 이 두 줄이 문자에서 통째로 죽어 있었다.
                _weave2 = woven_answer("확장 지점", _procedures, _cg2)
                assert _weave2 and "이 절이 아니라면" in _weave2, (_weave2 or "")[-200:]
                _embed_batch = find_procedure(_procedures, "확장 지점", count=3)
                assert len(_embed_batch) >= 2, _embed_batch
                assert any("확장 지점" in y["제목"] for y in _embed_batch),                     [y["제목"] for y in _embed_batch]

    # 조립이 곧 말이다. 관계를 엮으면 원문에 없던 문장이 나오고, 각 홉은
    # 전부 특정 엣지에서 온다 — 지어낸 것이 아니라 아는 것을 엮은 것이다.
    _art = {"역할": "요리사", "목표": None, "설명그래프": True, "개념엣지": [],
           "임계값": {"A_MIN": 0.50, "OK_MIN": 0.58}, "무관층": {}, "조문수": 0,
           "노드": {"쌀뜨물": ["쌀뜨물"], "멸치육수": ["멸치육수"],
                    "감칠맛": ["감칠맛"]},
           "메타": {n: {"community": "요리", "file": "김치찌개.md", "loc": None,
                        "type": "개념", "무게": 1.0, "빈도": 1, "문서수": 1,
                        "정의처": [], "출처": [], "법별": [],
                        "발췌": [{"글": "쌀뜨물을 쓰면 국물이 부드러워진다",
                                  "곳": "김치찌개.md"}]}
                    for n in ("쌀뜨물", "멸치육수", "감칠맛")},
           "엣지": [["쌀뜨물", "대체", "멸치육수"], ["멸치육수", "이유", "감칠맛"]]}
    _art = prepare_knowledge(_art)
    _path = linking_path(_art, "쌀뜨물", "감칠맛")
    assert len(_path) == 2, _path
    _stmt = fit_particle(explain_path(_art, _path))
    assert "관계다" not in _stmt, _stmt       # 말투 없는 폴백으로 떨어지지 않는다
    # 앞 홉은 연결형, 마지막 홉만 종결형. 이음말은 관계가 고른다.
    assert "대신할 수 있고" in _stmt and "이어진다" in _stmt, _stmt
    assert "그리고" not in _stmt, _stmt           # 늘 '그리고' 로 잇지 않는다
    assert "쌀뜨물은" in _stmt, _stmt             # 조사를 이름에 붙인다
    # 홉마다 주어가 바뀌므로 생략하면 안 된다. 생략하면 쌀뜨물이 감칠맛으로
    # 이어진다고 읽히는데, 실제로 이어지는 것은 멸치육수다.
    assert "멸치육수는 감칠맛" in _stmt, _stmt

    # 말투는 데이터다. 파일을 바꾸면 같은 그래프가 다른 언어로 말한다.
    # 엔진 코드는 한 줄도 안 바뀐다 — 그래프를 바꿔 도메인을 바꾸는 것과 같다.
    global dialect, relation_phrase
    _orig, _orig_relation = dialect, relation_phrase
    try:
        dialect = read_dialect("english")
        relation_phrase = dialect["관계말"]
        _s_zero = fit_particle(explain_path(_art, _path))
        assert "can replace" in _s_zero and "leads to" in _s_zero, _s_zero
        assert ", and " in _s_zero, _s_zero            # 이음말이 바뀐다
        assert "이다" not in _s_zero and "한다" not in _s_zero, _s_zero         # 한국어 어미가 안 샌다
        assert read_dialect("english")["조사붙임"] is False   # 조사 단계를 건너뛴다
    finally:
        dialect, relation_phrase = _orig, _orig_relation

    # 낱말 중간을 자르지 않는다: '해고가' 에서 '고가' 를 뽑으면 엉뚱한 곳으로 간다
    if os.path.exists(_abs("data/법지식/지식그래프.json")):
        law = prepare_knowledge(json.load(open(_abs("data/법지식/지식그래프.json"), encoding="utf-8")))
        assert ask(law, "해고가 뭐야")[2] == "해고"
        # 같은 노드인데 의도에 따라 다른 조문을 고른다
        hour = ask(law, "해고는 언제 할 수 있어?")[1]
        mid = ask(law, "해고가 뭐야")[1]
        assert "예고" in hour and hour != mid, (hour, mid)
        # 법 이름을 물으면 제1조(목적)을 준다 — 편·장 표시가 아니라
        assert "목적으로 한다" in ask(law, "근로기준법이 뭐야")[1]
        # 조사 뒤에 오는 낱말을 놓치지 않는다 ('국가에 손해배상' -> 손해배상)
        assert ask(law, "국가에 손해배상 청구할 수 있어?")[2] == "손해배상"
        # 공백을 넘어 붙이지 않는다 ('해고 예고 기간' 이 '예고기간' 으로 새지 않게)
        assert ask(law, "해고 예고 기간은 며칠이야")[2] == "해고"
        # 조각이 이기지 않는다 ('저작' 말고 '저작권')
        assert ask(law, "저작권 침해 형량이 어떻게 돼")[2] == "저작권"
        # 길이가 같으면 먼저 나온 것이 주제다
        assert ask(law, "계약 취소하고 싶은데")[2] == "계약"
        # 낱말 앞부분만 겹치는 것은 답이 아니다 ('양자역학' 안의 '양자').
        # 확신 없이 설명하지 말고 되묻거나 모른다고 해야 한다.
        assert ask(law, "양자역학이 뭐야")[0] in ("미지", "A")

    # 지식 그래프 대화: 주제를 가리지 않는다
    import subprocess
    if os.path.exists(_abs("data/예시_요리/지식그래프.json")):
        cook = prepare_knowledge(json.load(open(_abs("data/예시_요리/지식그래프.json"), encoding="utf-8")))
        tag, ans, node = ask(cook, "김치찌개 어떻게 만들어?")
        assert tag == "설명" and "김치" in ans, (tag, ans)
        assert ask(cook, "자동차 수리 방법")[0] == "미지"
        # 원문을 인용하되, 질문에 맞는 문장을 고른다.
        # 같은 노드인데 '뭐야' 와 '언제' 의 답이 달라야 한다.
        what = ask(cook, "두부가 뭐야")[1]
        when = ask(cook, "두부는 언제 넣어?")[1]
        assert "콩을 갈아" in what, what
        assert "마지막에 넣어야" in when, when
        assert what != when
        assert "—" in what and "—" in when          # 출처를 밝힌다
        assert len(cook["메타"]["두부"]["발췌"]) >= 2
        # 개념망이 자동으로 뽑혔고, 상위어가 하위어를 가로채지 않는다
        top = {(a, b) for a, r, b in cook.get("개념엣지", []) if r == "상위"}
        assert ask(cook, "멸치육수가 뭐야")[2] == "멸치육수"

    # GPU 를 쓰지 않는다 — 이 프로젝트의 전제다
    assert DEVICE == "cpu" or os.environ.get("KG_DEVICE")
    # 아래는 신경망일 때만 볼 수 있다. 문자 인코더에는 파라미터가 없어
    # AttributeError 로 죽었다 — 기본 인코더에서 자가검사가 끝까지 못 갔다.
    _inner_model = getattr(_model(), "_first_module", None)
    if _inner_model is not None:
        assert str(next(_inner_model().auto_model.parameters()).device) == DEVICE

    # 질문 의도를 가른다 (같은 자리면 긴 표현이 이긴다)
    assert intent("이거 어디 있어?") == "위치"
    assert intent("이거 어디서 써?") == "쓰는곳"
    assert intent("왜 이렇게 했어?") == "이유"
    assert intent("A랑 B 무슨 관계야?") == "경로"
    assert intent("뭐랑 관련 있어?") == "이웃"
    assert intent("그게 뭐야?") == "정의"

    # 관계 이름을 자연어로 읽는다
    assert "가져다" in relation_sentence("imports", "X", True)
    assert "호출" in relation_sentence("calls", "X", True)
    assert "관계다" in relation_sentence("모르는관계", "X", True)   # 모르면 그대로 읽는다

    # 조사를 받침에 맞춘다
    # 받침에 맞추고, 고른 뒤에는 이름에 붙인다 ('저작권 은' 은 기계 티가 난다)
    assert fit_particle("저작권 는 해고 을 다룹니다") == "저작권은 해고를 다룹니다"
    assert fit_particle("전세권 와 임대차 은") == "전세권과 임대차는"
    # ㄹ 받침은 '으로' 가 아니라 '로' 다 — 서울로·물로·법률로.
    # 받침표 인덱스가 한 칸만 밀려도 ㄹ 을 ㄷ 으로 읽어 예외가 안 걸린다.
    assert fit_particle("서울 으로") == "서울로"
    assert fit_particle("법률 으로") == "법률로"
    assert fit_particle("계약 으로") == "계약으로"      # 다른 받침은 '으로'
    assert fit_particle("침해 으로") == "침해로"        # 받침 없으면 '로'
    # 인용한 원문은 건드리지 않는다 — '그 밖에 이 법에' 의 '이' 는 조사가 아니다
    assert "그 밖에 이 법에" in ask(law, "저작권 침해하면 처벌받아?")[1]

    print("selfcheck ok")


def open_(path):
    """지식그래프.json 을 대화할 수 있는 상태로. graphify 것은 변환해서."""
    raw = json.load(open(path, encoding="utf-8"))
    # 지식짓기.py 가 만든 것은 이미 이 모양이다. graphify 것은 변환이 필요하다.
    return prepare_knowledge(raw if raw.get("설명그래프") else graphify_read(path))


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--check" in sys.argv:
        _selfcheck()
        sys.exit(0)

    if "--코딩" in sys.argv:
        if len(argv) < 1:
            print('사용법: python 설명.py --코딩 "판정 밴드를 추가하려면"')
            sys.exit(1)
        question = argv[-1]
        doc = argv[:-1] or ["docs/ko/development.md", "README.md", "docs/ko/graph-authoring.md"]
        group = read_procedure([f for f in doc if os.path.exists(_abs(f))])
        code = None
        if os.path.exists(_abs("graphify-out/graph.json")):
            code = open_("graphify-out/graph.json")
        template = dialect.get("_자세히")
        scale = 3 if (template and template.search(question)) else 1
        ans = woven_answer(question, group, code, scale)
        print(ans or "맞는 절차를 찾지 못했다.")
        sys.exit(0)

    if "--절차" in sys.argv:
        if len(argv) < 2:
            print('사용법: python 설명.py --절차 <문서.md 또는 폴더> "질문"')
            sys.exit(1)
        doc = [x for x in argv[:-1]]
        question = argv[-1]
        group = read_procedure(doc)
        print("절차 %d개 (표 %d개)"
              % (len(group), sum(1 for x in group if x.get("표"))))
        template = dialect.get("_자세히")
        scale = 3 if (template and template.search(question)) else 1
        x = find_procedure(group, question)
        print()
        print("Q %s" % question)
        print(procedure_answer(x, scale, question) if x else "  맞는 절차를 찾지 못했다.")
        sys.exit(0)

    if "--모름" in sys.argv:
        # 무엇을 더 받아와야 하는가. 엔진은 자기가 모르는 말을 이미 안다 —
        # 그것을 꺼내주면 wiki.py 가 그대로 받아온다. 검색 결과는 답이
        # 아니라 자료다(collectors/wiki.py 머리말). 이 명령은 '무엇을
        # 찾을지' 까지만 하고, 받는 것도 그래프에 넣는 것도 사람이 한다.
        #
        #   python explain.py --모름 문서그래프.json "오타 교정은 어떻게 동작해"
        #   python explain.py --모름 문서그래프.json --파일 물음.txt
        if len(argv) < 1:
            print('사용법: python explain.py --모름 <그래프.json> "질문" ...')
            print('        python explain.py --모름 <그래프.json> --파일 <물음.txt>')
            sys.exit(1)
        g = open_(_abs(argv[0]))
        questions = argv[1:]
        if "--파일" in sys.argv:
            workdir = sys.argv[sys.argv.index("--파일") + 1]
            questions = [x.strip() for x in io.open(_abs(workdir), encoding="utf-8")
                      if x.strip()]
        if not questions:
            print("물을 것이 없습니다.")
            sys.exit(1)
        acc = {}
        for q in questions:
            _meaning, _ans, topic = ask(g, q)
            for w in _unknown_words(g, q, topic):
                acc[w] = acc.get(w, 0) + 1
        if not acc:
            print("# 모르는 말이 없습니다. 받아올 것이 없습니다.")
            sys.exit(0)
        print("# 물음 %d개에서 모르는 말 %d개. 받으려면:" % (len(questions), len(acc)))
        print("#   python collectors/wiki.py " + " ".join(sorted(acc)[:8]))
        print("# 받은 뒤 data/웹 을 코퍼스에 넣고 build.py 로 다시 짓습니다.")
        for w, c in sorted(acc.items(), key=lambda x: -x[1]):
            print("%-16s %d번" % (w, c))
        sys.exit(0)

    if "--score" in sys.argv:
        if not argv:
            print("사용법: python 설명.py --score <지식그래프.json>")
            sys.exit(1)
        g = open_(_abs(argv[0]))
        r = grade_explain(g)
        print("설명 채점 — 원문이 정답지다. 사람이 라벨을 안 단다.")
        print("  노드 %d개 (발췌가 있는 것만)" % r["총"])
        n = max(r["총"], 1)
        print("  이름으로 물으면        %3d/%d (%.0f%%)  조회 경로가 사는가"
              % (r["이름"], r["총"], 100 * r["이름"] / n))
        q = max(r["물음"], 1)
        print("  이름을 지우고 물으면    %3d/%d (%.0f%%)  임베딩 매칭만의 실력"
              % (r["가림"], r["물음"], 100 * r["가림"] / q))
        print("  옳은 대목이 답에 있나   %3d/%d (%.0f%%)  쓰는 사람이 원하는 것"
              % (r["대목"], r["물음"], 100 * r["대목"] / q))
        print("  한 문장의 주인 수 평균  %.1f  (1.0 이면 정답이 하나로 정해진다)"
              % r["주인평균"])
        if r["틀린것"]:
            print()
            print("  주제를 놓친 예:")
            for n2, topic, sentence in r["틀린것"]:
                print("    %-10s -> %-10s  \"%s\"" % (n2, topic, sentence))
        sys.exit(0)

    if "--draw" in sys.argv:
        if not argv:
            print("사용법: python 지식.py --draw <지식그래프.json> [중심노드]")
            sys.exit(1)
        g = open_(_abs(argv[0]))
        m = knowledge_image(g, argv[1] if len(argv) > 1 else None)
        out_edges = os.path.splitext(_abs(argv[0]))[0] + ".mmd"
        open(out_edges, "w", encoding="utf-8").write(m + "\n")
        print("%s  (%d줄)" % (out_edges, len(m.splitlines())))
        print("  ```mermaid 블록에 넣거나 mermaid.live 에 붙이면 보인다.")
        sys.exit(0)

    if not argv:
        print("사용법: python 지식.py <지식그래프.json>")
        print("        python 지식짓기.py <폴더>  로 먼저 그래프를 짓는다.")
        sys.exit(1)
    ps = open_(_abs(argv[0]))
    print("[안내] 노드 %d · 엣지 %d   (종료 입력시 끝)"
          % (len(ps["노드"]), len(ps["엣지"])))
    relation = {}
    for _, r, _ in ps["엣지"]:
        relation[r] = relation.get(r, 0) + 1
    print("  관계: " + ", ".join("%s %d" % kv for kv in
                                 sorted(relation.items(), key=lambda t: -t[1])[:6]))
    dialogue_file = (sys.argv[sys.argv.index("--대화") + 1]
                if "--대화" in sys.argv else None)
    memory = (DialogueMemory.read(dialogue_file)
            if dialogue_file and os.path.exists(_abs(dialogue_file)) else DialogueMemory())
    if memory.turn:
        print("  [이어서] %d턴째 · 살아 있는 것: %s"
              % (memory.turn, ", ".join(memory.hottest()) or "없음"))
    while True:
        q = input("\n> ").strip()
        if q in ("종료", "q", ""):
            if dialogue_file:
                memory.save(dialogue_file, argv[0])
                print("  %s 에 저장했다." % dialogue_file)
            break
        if q.startswith("저장"):
            path = (q.split(None, 1)[1].strip() if len(q.split()) > 1
                    else (dialogue_file or "대화.json"))
            memory.save(path, argv[0])
            print("  %s 에 저장했다. 다음에 --대화 %s 로 이어서 하면 된다."
                  % (path, path))
            continue
        if q in ("기억", "맥락"):
            print("  지금 살아 있는 것: " + (", ".join(memory.hottest()) or "없음")
                  + "   (%d턴째)" % memory.turn)
            continue
        meaning, ans, topic = ask(ps, q, memory)
        memory.record_turn([topic], q, topic)
        print("  " + (ans or ""))
