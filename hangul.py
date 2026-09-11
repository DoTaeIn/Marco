# -*- coding: utf-8 -*-
"""한글 문법을 표가 아니라 **글자에서** 끌어낸다.

한글은 유니코드에 산수로 박혀 있다. 한 음절은 (초성, 중성, 종성) 셋으로
쪼개지고 종성이 있는지 없는지가 조사를 가른다. 그러니 낱말마다 조사를
적어 둘 이유가 없다 — 계산하면 된다. toss/es-hangul 이 하는 것이 이것이다.

우리는 그걸 안 하고 있었다. 세어 보니 이랬다.

    자모 산수(0xAC00, %% 28)   8개 파일에 따로   build · encoder · engine ·
                                              explain · codegen · 사전뽑기 ·
                                              목적그래프
    조사 짝표                  4벌
    조사 고치는 함수            3벌
    받침 판정                  4벌

표로 관리하니 표에 없는 것이 들어오면 말을 망가뜨렸다.

    조사고치기('철수이랑 간다', ['철수'])  ->  '철수가랑 간다'
    조사고치기('서울으로 간다', ['서울'])  ->  '서울으로 간다'

앞엣것은 '이랑' 이 표에 없어서 한 글자 '이' 를 잡아 '가' 로 뒤집은 것이고,
뒤엣것은 ㄹ 받침 예외가 아예 없던 것이다. 이번 판에 '이니까/니까' 와
'이네요/네요' 를 손으로 더했는데, 그렇게 더하는 일 자체가 증상이었다.

원리로 갈면 갈래가 둘뿐이다.

  진짜 짝 (넷)   은/는 · 이/가 · 을/를 · 과/와
                 소리가 아예 다른 것들이라 이건 적어 둘 수밖에 없다.

  덧나는 이/으   받침 뒤에서 '이' 나 '으' 가 앞에 돋는다.
                 이랑/랑 · 이라/라 · 이니까/니까 · 이네요/네요 · 이야/야 ·
                 으로/로 · 으며/며 · 으면/면 · 으로서/로서 ...
                 이건 규칙이라 적을 것이 없다. '이랑' 이 저절로 된다.

  ㄹ 예외        '으' 계열만, ㄹ 받침 뒤에서는 안 돋는다.
                 서울로 · 물로 (서울으로 · 물으로 가 아니다)

다른 언어를 붙일 때도 같은 자리다. 영어의 a/an 도 뒤에 오는 소리로
갈리는 같은 종류의 규칙이라 `문법` 아래에 나란히 두면 된다.
"""
import re

_start, _end = 0xAC00, 0xD7A3
_ONSETS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_NUCLEI = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_CODAS = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def is_hangul(char):
    return bool(char) and _start <= ord(char[0]) <= _end


def decompose(char):
    """음절 하나 -> (초성, 중성, 종성). 종성이 없으면 ''. 한글이 아니면 None."""
    if not is_hangul(char):
        return None
    k = ord(char[0]) - _start
    return (_ONSETS[k // 588], _NUCLEI[(k % 588) // 28], _CODAS[k % 28].strip())


def compose(onset, nucleus, coda=""):
    """(초성, 중성, 종성) -> 음절 하나."""
    return chr(_start + _ONSETS.index(onset) * 588
               + _NUCLEI.index(nucleus) * 28
               + (_CODAS.index(coda) if coda else 0))


def batchim(phrase):
    """낱말 끝 글자의 종성. 없으면 ''. 한글이 아니면 None.

    None 과 '' 는 다르다. None 은 '판단할 수 없다'(영문·숫자)이고 '' 는
    '받침이 없다'(사과)다. 이걸 섞으면 'CCTV을' 같은 것이 나간다."""
    if not phrase or not is_hangul(phrase[-1]):
        return None
    return _CODAS[(ord(phrase[-1]) - _start) % 28].strip()


def strip_batchim(phrase):
    """끝 글자의 받침을 뗀 말. 받침이 없으면 그대로.

    과거 관형형이 이 꼴이다 — '만든' 의 ㄴ 은 낱글자로 안 서고 받침으로
    붙어 있어서, 글자 단위로 자르면 안 보인다(만든 -> 만드, 나타낸 ->
    나타내). 사전 정의문이 '…만든 것.' 으로 끝나는 일이 흔하다."""
    ㄴ = batchim(phrase)
    if not ㄴ:
        return phrase
    sec, mid, _ = decompose(phrase[-1])
    return phrase[:-1] + compose(sec, mid)


def flatten_jamo(phrase):
    """한글을 자모로 편다. '해고' -> ㅎㅐㄱㅗ. 한글이 아닌 글자는 그대로.

    음절로 자르면 '해고' 와 '해구' 가 한 글자도 안 겹친다. 자모로 펴면
    ㅗ/ㅜ 하나 차이다 — 오타도 자모 하나 차이라 글자 단위로는 안 보인다.

    글자마다 `분해` 를 부르지 않고 고리를 여기 둔 이유. 인코더 안쪽
    고리라 글자마다 함수를 부르면 66% 느려진다(44ms -> 73ms / 2000회).
    고리째로 옮기면 부르는 쪽은 한 번만 부르니 값이 같다."""
    out = []
    for c in phrase:
        k = ord(c) - _start
        if 0 <= k < 11172:
            out.append(chr(0x1100 + k // 588))
            out.append(chr(0x1161 + (k % 588) // 28))
            if k % 28:
                out.append(chr(0x11A7 + k % 28))
        else:
            out.append(c)
    return "".join(out)


def jamo_index(phrase):
    """자모를 번호로 편다. [초, 중, 종] 셋씩. 오타 거리를 잴 때 쓴다."""
    out = []
    for c in phrase:
        k = ord(c) - _start
        if 0 <= k < 11172:
            out += [k // 588, (k % 588) // 28, k % 28]
        else:
            out.append(c)
    return out


def onset(phrase):
    """낱말 -> 초성만. 한글이 아닌 글자는 그대로 둔다.

    초성 검색('ㄱㅁㅇ' -> '고맙읍')에 쓸 자리다. 지금은 안 쓰지만 자모를
    한곳에 모은 김에 같이 둔다 — 밖에서 또 0xAC00 을 쓰지 않게."""
    return "".join(decompose(c)[0] if is_hangul(c) else c for c in phrase)


def _vowel_join(stem, grammar, tense=None):
    """Apply the pack's harmony/contraction rules to a known stem, not a guess."""
    rule = grammar["vowel_join"]
    for suffix, replacements in rule.get("overrides", {}).items():
        if stem.endswith(suffix):
            return [(stem[:-len(suffix)] + replacement, ["vowel-override"])
                    for replacement in replacements]
    onset_, vowel, coda = decompose(stem[-1])
    harmony_vowel = vowel
    if not coda and vowel in rule.get("elide", []):
        previous = decompose(stem[-2]) if len(stem) > 1 else None
        harmony_vowel = previous[1] if previous else None
    ending_vowel = rule.get("after_tense", {}).get(tense)
    if ending_vowel is None:
        ending_vowel = rule["bright"] if harmony_vowel in rule["bright_vowels"] else rule["dark"]
    if coda:
        return [(stem + compose(rule["onset"], ending_vowel), ["vowel-harmony"])]
    if vowel in rule.get("elide", []):
        return [(stem[:-1] + compose(onset_, ending_vowel), ["vowel-elision"])]
    contraction = rule.get("contractions", {}).get(vowel + ending_vowel)
    expanded = stem + compose(rule["onset"], ending_vowel)
    if contraction:
        joined = stem[:-1] + compose(onset_, contraction["vowel"])
        forms = [(joined, ["vowel-contraction"])]
        if contraction.get("optional"):
            forms.append((expanded, ["vowel-harmony"]))
        return forms
    return [(expanded, ["vowel-harmony"])]


def inflect(stem, tense, ending, grammar, *, kind):
    """Realize pack-declared morphemes using Hangul arithmetic.

    The model supplies a known stem, class, tense and ending; this function
    never strips an arbitrary input word to invent a lemma. Rules, allomorphs,
    vowel classes and lexical exceptions are supplied by the language pack.
    Return alternative spellings with their operation paths. No neural model
    or expanded sentence-template collection is created.
    """
    if not stem or not all(is_hangul(char) for char in stem):
        raise ValueError("inflection_requires_hangul_stem")
    if kind not in grammar.get("kinds", []):
        raise ValueError("unsupported_inflection_kind")
    features = {"kind": kind, "tense": tense}
    try:
        suffix_rule = next(rule for rule in grammar["endings"][ending]
                           if all(features.get(key) == value for key, value in rule.get("when", {}).items()))
        steps = [(step, None) for step in grammar["tenses"][tense]]
        steps += [(step, tense) for step in suffix_rule["steps"]]
    except (KeyError, StopIteration) as exc:
        raise ValueError("unsupported_inflection_features") from exc
    forms = [(stem, [])]
    for step, after_tense in steps:
        following = []
        for word, trace in forms:
            op = step["op"]
            if op == "vowel":
                following.extend((new, trace + path) for new, path in _vowel_join(word, grammar, after_tense))
                continue
            if op == "append":
                new = word + step["text"]
            elif op == "coda":
                a, b, c = decompose(word[-1])
                if c:
                    raise ValueError("inflection_coda_already_occupied")
                new = word[:-1] + compose(a, b, step["value"])
            elif op == "coda_suffix":
                a, b, c = decompose(word[-1])
                if c in step.get("drop_codas", []):
                    word, c = word[:-1] + compose(a, b), ""
                new = (word + step["closed"] if c else
                       word[:-1] + compose(a, b, step.get("coda", "")) + step["open"])
            elif op == "epenthetic":
                c = batchim(word)
                if c in step.get("drop_codas", []):
                    word, c = strip_batchim(word), ""
                new = word + (step["closed"] if c and c not in step.get("exceptions", []) else step["open"])
            else:
                raise ValueError("unsupported_inflection_operation")
            following.append((new, trace + [op]))
        forms = list({word: (word, trace) for word, trace in following}.values())
        if len(forms) > grammar["max_forms"]:
            raise ValueError("inflection_form_limit")
    return [{"text": word, "operations": trace} for word, trace in forms]


# ── 원문을 보존하는 절 경계 ───────────────────────────────────────────
_protected_clause_text = re.compile(
    r'```[\s\S]*?(?:```|$)|`[^`\n]*(?:`|$)|"(?:\\.|[^"\\])*(?:"|$)'
    r"|(?<!\w)'(?:\\.|[^'\\])*'(?!\w)"
    r'|“[^”]*(?:”|$)|‘[^’]*(?:’|$)|https?://[^\s<>]+')
_clause_break = re.compile(r"[.!?,;\n。？！]|[^\S\n]+")


def canonical_clauses(literal, grammar):
    """팩이 선언한 연결형을 해석용 후보로만 되돌린다. 원문은 바꾸지 않는다.

    '고'가 있다고 사실이 되지는 않는다. 되돌린 **전체 절**이 언어 모델의
    슬롯·서술어와 맞을 때만 호출자가 채택한다. 조건·인용·추측 어미를
    평서문으로 바꾸는 기본값은 없으며, 빈 팩이면 원문만 반환한다.
    """
    yield literal, None
    for rule in grammar.get("canonical_endings", []):
        suffix = rule["suffix"]
        if not suffix or not literal.endswith(suffix):
            continue
        stem = literal[:-len(suffix)]
        if not stem or stem[-1].isspace():
            continue
        for ending in rule["replacements"]:
            yield stem + ending, rule


def clause_spans(text, grammar=None, *, commas=False, accept_prefix=None, inflected_boundary=None):
    """절의 {start, end, text}. end는 제외, 위치는 원문 Unicode 문자 기준.

    문장부호와 연결어미의 경계 탐색을 공유한다. 검색은 전체 문장에 더할
    후보로 쓰고, 추론은 accept_prefix로 완전한 절인지 검사한다. '창고'의
    '고' 같은 명사 꼬리는 접미사만으로 절이라고 확정할 수 없기 때문이다.
    소수점·인용문·코드·URL 내부는 쪼개지 않는다. grammar가 없으면 한국어
    어미 지식을 코드 옆에서 몰래 읽지 않고 문장부호만 처리한다.
    """
    grammar = grammar or {}
    suffixes = tuple(grammar.get("candidate_suffixes", []))
    continuations = tuple(grammar.get("continuation_prefixes", []))
    protected = iter(_protected_clause_text.finditer(text))
    protected_range = next(protected, None)
    spans, start = [], 0

    def emit(end):
        nonlocal start
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            spans.append({"start": left, "end": right, "text": text[left:right]})

    for boundary in _clause_break.finditer(text):
        pos = boundary.start()
        while protected_range is not None and protected_range.end() <= pos:
            protected_range = next(protected, None)
        if protected_range is not None and protected_range.start() <= pos < protected_range.end():
            continue
        char = boundary.group()
        if char.isspace() and char != "\n":
            if not suffixes and inflected_boundary is None:
                continue
            word_start = pos
            while word_start > start and not text[word_start - 1].isspace():
                word_start -= 1
            word = text[word_start:pos]
            if not (any(word.endswith(s) and len(word) > len(s) for s in suffixes)
                    or (inflected_boundary is not None and inflected_boundary(word))):
                continue
            if any(text.startswith(tail, boundary.end()) for tail in continuations):
                continue
            if accept_prefix is not None and not accept_prefix(text[start:pos].strip()):
                continue
        else:
            if char in ".," and pos > 0 and pos + 1 < len(text):
                if text[pos - 1].isdigit() and text[pos + 1].isdigit():
                    continue
            if char == "," and not commas:
                if not any(text[start:pos].endswith(s) for s in grammar.get("comma_after_suffixes", [])):
                    continue
        emit(pos)
        start = boundary.end()
    emit(len(text))
    return spans


# ── 낱말 꼬리 ─────────────────────────────────────────────────────────
# 조사와 어미. engine.py 에 흩어져 있던 것을 여기로 모은다 — 이건 도메인
# 지식이 아니라 한국어 규칙이라, 자모·조사와 한자리에 있어야 고칠 때 한
# 군데만 보면 된다.
particles = ("으로써", "으로서", "이라는", "에서는", "에서도", "라는", "에서", "에게", "한테",
        "까지", "부터", "처럼", "보다", "이나", "거나", "이며", "으로", "로서", "로써",
        "와의", "과의", "이라", "의", "을", "를", "은", "는", "이", "가", "도", "만",
        "과", "와", "로", "에")
endings = ("하지", "하는", "하여", "한", "된", "되는", "스러운", "스럽게", "있어", "없어")
# 용언이 끝나는 소리. 이걸로 끝나면 명사가 아니라 서술어로 본다.
verb_ends = ("지", "기", "여", "며", "면", "고", "서", "게", "히", "이", "어", "아", "나")

# ── 예/아니오 ─────────────────────────────────────────────────────────
# 되묻기에 답하는 말. 사람이 실제로 쓰는 꼴을 다 적는다 — 'ㅇㅇ' 이 빠져
# 있어서 되묻고도 '맞다' 를 못 알아들은 적이 있다.
yes_words = ("네", "예", "맞다", "맞습니다", "맞아요", "맞아", "그렇습니다", "그래요",
        "그래", "응", "어", "그렇죠", "바로 그겁니다", "그 말입니다", "ㅇㅇ",
        "맞음", "yes", "y")
no_words = ("아니", "아뇨", "아닙니다", "아니요", "틀렸", "아냐", "no", "n")


# 소리가 아예 다른 짝. 이 넷만 적어 둔다. 앞이 받침 있는 쪽이다.
_mate = (("은", "는"), ("이", "가"), ("을", "를"), ("과", "와"))
# 받침 뒤에서 앞에 돋는 소리. '으' 는 ㄹ 받침 뒤에서는 안 돋는다.
_surplus = ("이", "으")


def pick_particle(phrase, mate):
    """받침을 보고 조사를 고른다. 짝은 '은/는' 처럼 '받침형/민형' 으로 준다.

        조사고르기('책', '은/는')   -> '은'
        조사고르기('사과', '은/는') -> '는'
        조사고르기('서울', '으로/로') -> '로'      (ㄹ 예외)
        조사고르기('책', '으로/로')   -> '으로'

    한글이 아니면 민형을 준다 — 'CCTV은' 보다 'CCTV는' 이 덜 틀린다."""
    with_batchim, plain = mate.split("/") if isinstance(mate, str) else mate
    ㄴ = batchim(phrase)
    if not ㄴ:
        return plain
    if with_batchim[:1] == "으" and ㄴ == "ㄹ":
        return plain
    return with_batchim


def attach_particle(phrase, particle):
    """낱말 + 조사 -> 맞는 꼴로 붙인 말. 조사는 어느 쪽 꼴로 줘도 된다.

        조사붙이기('철수', '이랑') -> '철수랑'
        조사붙이기('책', '랑')     -> '책이랑'
    """
    return phrase + _fitted_particle(phrase, particle)


def _fitted_particle(phrase, particle):
    """조사 하나를 그 낱말에 맞는 꼴로 바꾼다. 조사가 아니면 그대로."""
    for with_batchim, plain in _mate:
        if particle == with_batchim or particle == plain:
            return pick_particle(phrase, (with_batchim, plain))
    for add in _surplus:
        if particle.startswith(add) and len(particle) > 1:
            return pick_particle(phrase, (particle, particle[1:]))
        # 민형으로 적혀 있으면 받침 뒤에서 돋워 준다. '책' + '랑' -> '책이랑'
    if particle not in _epenthetic:
        return particle              # '에·에는·까지·도·만' 은 돋지 않는다
    ㄴ = batchim(phrase)
    if not ㄴ:
        return particle
    add = "으" if particle[:1] == "로" else "이"
    if add == "으" and ㄴ == "ㄹ":
        return particle
    return add + particle


# 조사로 볼 수 있는 것들. 낱말 뒤에 붙어 있을 때만 본다.
# 이 목록은 '어떤 소리가 조사냐' 지 '어떤 낱말에 무엇이 붙냐' 가 아니다 —
# 낱말마다 적는 표가 아니라서 늘어나지 않는다.
_particles = ("이랑", "랑", "이라고", "라고", "이라는", "라는", "이라", "라",
          "이니까", "니까", "이네요", "네요", "이야", "야", "이나", "나",
          "으로써", "로써", "으로서", "로서", "으로", "로",
          "은", "는", "이", "가", "을", "를", "과", "와",
          # 아래는 꼴이 안 바뀌는 조사다. _epenthetic 에 없으므로 받침이
          # 있어도 그대로 붙는다. 낱말 자리를 가리는 데 꼭 필요하다 —
          # 없으면 '다섯 개만' 의 '개' 가 낱말로 안 보인다.
          "에서", "에게", "한테", "부터", "까지", "마다", "보다", "처럼",
          "에", "의", "도", "만")
_longest_first = tuple(sorted(_particles, key=len, reverse=True))
# 받침 뒤에서 앞에 '이/으' 가 돋는 조사. 여기 없는 조사('에·까지·도·만')는
# 받침이 있어도 그대로 붙는다 — 그러지 않으면 '가래질이에는' 이 나온다.
_epenthetic = frozenset(("랑", "라", "라고", "라는", "니까", "네요", "야", "나",
                         "로", "로서", "로써"))


def strip_particle(tail):
    """낱말 뒤에 남은 조사 하나를 뗀다. 조사가 아니면 그대로.

        조사떼기('로 요약해줘')  -> ' 요약해줘'
        조사떼기('만 추출해줘')  -> ' 추출해줘'
        조사떼기('로봇을 봤다')  -> '로봇을 봤다'   (로봇은 낱말이다)

    낱말의 일부를 조사로 오해하지 않도록, 조사 뒤가 한글이면 떼지 않는다."""
    for particle in _longest_first:
        if tail.startswith(particle) and not is_hangul(tail[len(particle):len(particle) + 1]):
            return tail[len(particle):]
    return tail


def fix_particles(sentence, words):
    """치환된 낱말 뒤의 조사를 받침에 맞게 고친다.

    템플릿에 조사를 박아두면 '방위의사은' 같은 것이 나온다. 노드 이름이
    무엇이 들어올지 미리 알 수 없으므로 조립 후에 고치는 편이 낫다.

    긴 조사부터 본다. 짧은 것부터 보면 '철수이랑' 에서 '이' 를 잡아
    '철수가랑' 을 만든다 — 실제로 그렇게 깨져 있었다."""
    for value in sorted({x for x in words if x}, key=len, reverse=True):
        if batchim(value) is None:
            continue
        i = 0
        while True:
            i = sentence.find(value, i)
            if i < 0:
                break
            rear = i + len(value)
            for art in _longest_first:
                if not sentence.startswith(art, rear):
                    continue
                # 조사 뒤가 또 한글이면 조사가 아니라 다음 낱말일 수 있다.
                # '철수이것' 의 '이' 를 조사로 보면 안 된다.
                other = sentence[rear + len(art):rear + len(art) + 1]
                if other and is_hangul(other) and len(art) == 1:
                    continue
                correct = _fitted_particle(value, art)
                sentence = sentence[:rear] + correct + sentence[rear + len(art):]
                break
            i = rear
    return sentence


def swap_word(sentence, old, new):
    """문장 속 낱말 하나를 갈아 끼우고, 뒤따르는 조사를 새 낱말에 맞춰 다시 고른다.

        낱말갈기('흉기를 들고 있었습니다', '흉기', '식칼') -> '식칼을 들고 있었습니다'

    낱말만 갈고 문법을 앞 낱말 것 그대로 들고 오면 '식칼를' 처럼 아무도
    쓰지 않는 말이 된다. 개념망으로 별칭을 불릴 때 이 자리를 안 거쳐서
    실제로 그런 별칭이 만들어지고 있었다."""
    if not old or old not in sentence:
        return sentence
    return fix_particles(sentence.replace(old, new), [new])


def word_spans(sentence, word):
    """문장에서 그 낱말이 '낱말로' 나오는 자리들. 부분 문자열은 빼고.

        낱말자리('가격을 봤다', '가격')    -> [(0, 2)]
        낱말자리('가격표를 봤다', '가격')  -> []        (가격표는 다른 말이다)

    한국어는 조사를 붙여 쓰므로 뒤에 한글이 오는 것만으로는 못 가른다.
    뒤에 오는 것이 조사이거나, 공백이거나, 문장 끝일 때만 낱말로 본다."""
    out, i = [], 0
    while True:
        i = sentence.find(word, i)
        if i < 0:
            return out
        rear = i + len(word)
        before = sentence[i - 1:i]
        rest = sentence[rear:]
        if (not before or not is_hangul(before)) and (
                not rest or not is_hangul(rest[0])
                or any(rest.startswith(p) and not is_hangul(rest[len(p):len(p) + 1])
                       for p in _longest_first)):
            out.append((i, rear))
        i = rear


def _selfcheck():
    assert decompose("값") == ("ㄱ", "ㅏ", "ㅄ"), decompose("값")
    assert decompose("가") == ("ㄱ", "ㅏ", ""), decompose("가")
    assert decompose("A") is None
    assert compose("ㄱ", "ㅏ", "ㅄ") == "값" and compose("ㄱ", "ㅏ") == "가"
    assert batchim("책") == "ㄱ" and batchim("사과") == "" and batchim("CCTV") is None
    assert strip_batchim("만든") == "만드" and strip_batchim("나타낸") == "나타내"
    assert strip_batchim("나타내") == "나타내"
    assert onset("고맙습니다") == "ㄱㅁㅅㄴㄷ"
    assert flatten_jamo("해고") != flatten_jamo("해구") and len(flatten_jamo("해고")) == 4
    assert jamo_index("가")[:3] == [0, 0, 0] and len(jamo_index("값")) == 3
    # 낱말 꼬리와 예/아니오도 여기 있어야 한다. engine 이 이걸 들고 있으면
    # 한국어 규칙이 두 군데로 갈린다.
    assert "은" in particles and "는" in particles and "하는" in endings
    assert "ㅇㅇ" in yes_words and "아니요" in no_words
    assert not (set(yes_words) & set(no_words)), "예와 아니오가 겹친다"

    assert pick_particle("책", "은/는") == "은" and pick_particle("사과", "은/는") == "는"
    # ㄹ 예외. 이게 없어서 '서울으로' 가 나갔다.
    assert pick_particle("서울", "으로/로") == "로", pick_particle("서울", "으로/로")
    assert pick_particle("물", "으로/로") == "로"
    assert pick_particle("책", "으로/로") == "으로"
    assert pick_particle("부산", "으로/로") == "으로"   # ㄴ 받침은 돋는다
    # 한글이 아니면 민형. 'CCTV을' 보다 'CCTV를' 이 덜 틀리다.
    assert pick_particle("CCTV", "을/를") == "를"

    assert attach_particle("철수", "이랑") == "철수랑", attach_particle("철수", "이랑")
    assert attach_particle("책", "랑") == "책이랑", attach_particle("책", "랑")

    # 표에 없던 조사가 말을 망가뜨리던 자리
    assert fix_particles("철수이랑 간다", ["철수"]) == "철수랑 간다"
    assert fix_particles("서울으로 간다", ["서울"]) == "서울로 간다"
    assert fix_particles("물으로 씻는다", ["물"]) == "물로 씻는다"
    assert fix_particles("부산으로 간다", ["부산"]) == "부산으로 간다"
    # 예전 판이 하던 일은 그대로 해야 한다
    assert fix_particles("책를 읽는다", ["책"]) == "책을 읽는다"
    assert fix_particles("사과을 먹는다", ["사과"]) == "사과를 먹는다"
    assert fix_particles("연필가 있다", ["연필"]) == "연필이 있다"
    assert fix_particles("봤어요이니까 그렇다", ["봤어요"]) == "봤어요니까 그렇다"
    # 조사가 아닌 것은 안 건드린다
    assert fix_particles("철수 이것 봐", ["철수"]) == "철수 이것 봐"
    assert fix_particles("철수이것", ["철수"]) == "철수이것", fix_particles("철수이것", ["철수"])
    # 낱말을 갈면 조사도 같이 간다. 안 그러면 '식칼를' 이 별칭이 된다.
    assert swap_word("흉기를 들고 있었습니다", "흉기", "식칼") == "식칼을 들고 있었습니다"
    assert swap_word("흉기가 있었습니다", "흉기", "각목") == "각목이 있었습니다"
    assert swap_word("흉기를 들었다", "없는말", "식칼") == "흉기를 들었다"
    # 짝도 없고 돋지도 않는 조사는 그대로 붙는다
    assert attach_particle("가래질", "에는") == "가래질에는"
    assert attach_particle("흙", "까지") == "흙까지"
    assert attach_particle("책", "랑") == "책이랑"          # 이건 돋는다
    assert attach_particle("서울", "로") == "서울로"        # ㄹ 예외
    assert attach_particle("책", "로") == "책으로"
    # 낱말 자리. 부분 문자열은 낱말이 아니다.
    assert word_spans("가격을 봤다", "가격") == [(0, 2)]
    assert word_spans("가격표를 봤다", "가격") == []
    assert word_spans("흉기를 들고 있었습니다", "흉기") == [(0, 2)]
    assert word_spans("살상흉기를 들었다", "흉기") == []
    assert word_spans("결과 가 좋다", "결과") == [(0, 2)]
    print("자가검사 ok")


if __name__ == "__main__":
    _selfcheck()
