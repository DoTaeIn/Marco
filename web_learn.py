# -*- coding: utf-8 -*-
"""열린 웹에서 주워온 지식을 논증 그래프에 얹는다.

위키백과만 쓰면 "권위 있는 출처 한 곳"에 기댄다. 열린 웹은 그 제한이 없는
대신 아무 글이나 들어온다. 그래서 이 파일은 네 가지를 지킨다.

1. 주워온 문장은 원본 .kg 에 쓰지 않는다. 옆의 .수집.jsonl 에만 쌓는다.
   사람이 쓴 뼈대와 기계가 주워온 살이 한 파일에 섞이면 되돌릴 수가 없다.
   .학습.jsonl / .미지.log 와 같은 자리, 같은 규칙이다.
2. 출처 없는 문장은 넣지 않는다. 노드마다 출처가 붙고, engine 은 판정이
   인정/B1 일 때 그 출처를 답에 같이 내보낸다. 주워온 지식일수록 근거가
   남아야 한다.
3. 같은 주제를 말하는 출처가 여럿이면 증명 엣지가 그 수만큼 붙는다.
   교차검증은 따로 만든 장치가 아니라 원래 쓰던 논증 구조 그대로다.
4. 검색 결과의 짧은 발췌는 주소를 찾는 데만 쓴다. 원문 페이지를 내려받아
   완결된 문장만 지식 노드로 만들고, 답은 그 문장들을 골라 조립한다.
   잘린 `...`를 문장인 척 저장하거나 임의로 뒷말을 지어내지 않는다.

수집량·동시 쓰기·재수집 간격에는 운영 상한이 있다. KG_LEARN_MAX_TOPICS,
KG_LEARN_MAX_RECORDS, KG_LEARN_MAX_BYTES, KG_LEARN_COOLDOWN 환경변수로
배포 규모에 맞게 조정할 수 있다.

인코더는 KG_ENCODER=문자 를 기본으로 둔다. 토큰을 쓰지 않는다.
"""
import html
from html.parser import HTMLParser
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

os.environ.setdefault("KG_ENCODER", "문자")   # 토큰 없는 인코더가 이 파일의 기본값이다

import engine as eng
from encoder import _vec


# ── 운영 경계 ────────────────────────────────────────────────────────────
# 배포마다 다를 수 있는 값은 환경변수로 조절한다. 코드의 기본값은 무한 성장을
# 막는 안전망이고, 지식의 의미나 방향을 정하는 도메인 규칙이 아니다.
def _env_int(name, default, min_n=1):
    try:
        return max(int(os.environ.get(name, default)), min_n)
    except (TypeError, ValueError):
        return default


max_topic = lambda: _env_int("KG_LEARN_MAX_TOPICS", 200)
max_per_topic = lambda: _env_int("KG_LEARN_MAX_RECORDS", 20)
collect_max_byte = lambda: _env_int("KG_LEARN_MAX_BYTES", 5 * 1024 * 1024)
recollect_wait_sec = lambda: _env_int("KG_LEARN_COOLDOWN", 300)


class LearnFailed(RuntimeError):
    pass


class CollectLock:
    """동시에 같은 JSONL을 쓰지 못하게 하는 작은 파일 잠금."""
    def __init__(self, path):
        self.path = path + ".lock"
        self.fd = None

    def __enter__(self):
        for rnd in range(2):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, ("%d %d\n" % (os.getpid(), int(time.time()))).encode("ascii"))
                return self
            except FileExistsError as e:
                try:
                    stale = time.time() - os.path.getmtime(self.path) > 120
                except FileNotFoundError:
                    continue
                if stale and rnd == 0:
                    try:
                        os.unlink(self.path)
                    except FileNotFoundError:
                        pass
                    continue
                raise LearnFailed("같은 지식 파일을 다른 학습 작업이 갱신 중입니다") from e
            except OSError as e:
                if self.fd is not None:
                    os.close(self.fd)
                    self.fd = None
                raise LearnFailed("수집 잠금 파일을 만들 수 없습니다: %s" % e) from e

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


# ── 살균 ────────────────────────────────────────────────────────────────
# 진짜 손상은 개행·태그·제어문자다. 한 줄로 뭉개지 않으면 .kg 로 내보낼 때
# 줄이 갈라지고, 태그가 남으면 그게 그대로 임베딩에 들어간다.
#
# '|' 와 '#' 은 .kg 의 구분자·주석이라 예전 방식(원본 .kg 에 직접 주입)에서는
# 문장을 조용히 쪼개고 잘랐다. 여기서는 텍스트를 JSON 에 담으므로 그 위험이
# 구조적으로 사라진다 — 문자를 바꿔서 막는 것보다 이게 낫다. 원문을 훼손하지
# 않기 때문이다. .kg 로 내보낼 때만 kg안전=True 로 막는다.
_control = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_tg = re.compile(r"<[^>]+>")


def sanitize(txt, max_n=700, kg_safe=False):
    """주워온 문자열을 노드 예시로 쓸 수 있는 한 줄로 만든다."""
    # 태그는 공백이 아니라 빈 문자열로 지운다. 검색 스니펫은 질의어를 굵게
    # 표시하는데, <b>가</b>격은 처럼 낱말 중간에 걸리면 공백 치환이 낱말을 쪼갠다.
    txt = html.unescape(_tg.sub("", txt or ""))
    txt = _control.sub(" ", txt)
    txt = re.sub(r"\s+", " ", txt).strip().strip('"').strip()
    if kg_safe:
        # .kg 한 줄로 나갈 때만. 뜻을 해치지 않는 최소 치환.
        txt = txt.replace("|", "／").replace("#", "＃")
    return txt[:max_n].strip()


def kg_line(name, sentences, src=None):
    """노드 하나를 .kg 한 줄로. 내보내기용이며 평소 경로에는 쓰이지 않는다."""
    head = name + ("@" + src if src else "")
    return '%s: %s' % (head, " | ".join('"%s"' % sanitize(s, kg_safe=True) for s in sentences))


# ── 검색 ────────────────────────────────────────────────────────────────
_link = re.compile(r"href=\"(https?://[^\"]+)\"[^>]*class='result-link'", re.I)
_snippet = re.compile(r"class='result-snippet'[^>]*>(.*?)</td>", re.DOTALL | re.I)


def _real_url(url):
    """DuckDuckGo 우회 링크면 원문 주소를 꺼낸다."""
    p = urllib.parse.urlparse(html.unescape(url))
    if "duckduckgo.com" in p.netloc:
        q = urllib.parse.parse_qs(p.query)
        if q.get("uddg"):
            return q["uddg"][0]
    return urllib.parse.urlunparse(p)


def search(query, count=10, min_length=40):
    """열린 웹 검색. 원문 URL과 검색 발췌를 돌려준다.

    발췌는 관련 결과를 거르는 힌트일 뿐 지식으로 저장하지 않는다. 여러 URL을
    받아야 원문 교차검증이 가능해지므로 기본값을 10 으로 둔다."""
    req = urllib.request.Request(
        "https://lite.duckduckgo.com/lite/",
        data=urllib.parse.urlencode({"q": query}).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8", "replace")

    link = [_real_url(u) for u in _link.findall(body)]
    chunk = [sanitize(s) for s in _snippet.findall(body)]
    out, seen = [], set()
    for i, txt in enumerate(chunk):
        if len(txt) < min_length or txt in seen:
            continue                       # 너무 짧은 것은 근거가 못 된다
        seen.add(txt)
        url = link[i] if i < len(link) else ""
        if not url:
            continue
        out.append({"url": url, "도메인": urllib.parse.urlparse(url).netloc,
                    "발췌": txt})
        if len(out) >= count:
            break
    return out


class _BodyExtractor(HTMLParser):
    """광고·메뉴·스크립트를 빼고 문서 본문 블록만 모은다."""
    block_tag = {"p", "article", "section", "main", "h1", "h2", "h3", "li", "blockquote"}
    drop_tag = {"script", "style", "noscript", "svg", "canvas", "nav", "footer", "header", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.dropped = 0
        self.block = []
        self.cur = []

    def handle_starttag(self, tag, _attrs):
        tag = tag.lower()
        if tag in self.drop_tag:
            self.dropped += 1
        elif not self.dropped and tag in self.block_tag and self.cur:
            self._close()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.drop_tag:
            self.dropped = max(0, self.dropped - 1)
        elif not self.dropped and tag in self.block_tag:
            self._close()

    def handle_data(self, data):
        if not self.dropped:
            self.cur.append(data)

    def _close(self):
        txt = sanitize(" ".join(self.cur), max_n=12000)
        if len(txt) >= 30:
            self.block.append(txt)
        self.cur = []

    def emit_end(self):
        self._close()
        return list(dict.fromkeys(self.block))


_sentence = re.compile(r"[^.!?。！？\n]{12,}[.!?。！？](?=\s|$)")


def complete_sentences(txt, topic=None, max_sentence=None):
    """원문 블록의 완결 문장을 순서대로 고른다. 주제가 있으면 관련 문장만 고른다."""
    out = []
    for m in _sentence.finditer(txt or ""):
        sentence = sanitize(m.group(0), max_n=1500)
        if (sentence.endswith("...") or sentence.endswith("…")
                or (topic and not topic_related(topic, sentence))
                or sentence in out):
            continue
        out.append(sentence)
        if max_sentence and len(out) >= max_sentence:
            break
    return out


def read_source(url, topic, max_byte=2 * 1024 * 1024, max_sentence=None, passage_include=False):
    """웹 페이지 원문을 읽어 (제목, 완결 지식 문장들)을 돌려준다.

    `주제`는 표제어 하나(문자열)이거나 `물음낱말`이 뽑은 내용 낱말 묶음이다.
    묶음일 때는 낱말 겹침으로 대목을 고른다."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(max_byte + 1)
        if len(raw) > max_byte:
            raw = raw[:max_byte]
        charset = r.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, "replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = sanitize(title_match.group(1), max_n=300) if title_match else ""
    parser = _BodyExtractor()
    parser.feed(text)
    is_related = _related_verdict(topic)
    sentences, passages = [], []
    for block in parser.emit_end():
        block_sentences = complete_sentences(block)
        # 주제를 말하는 문장이 하나라도 있는 문단은 대명사·후속 설명까지 모두
        # 같은 지식 대목이다. 문장마다 주제 낱말을 반복하도록 요구하면 맥락이 잘린다.
        if not block_sentences or not is_related(block_sentences):
            continue
        passages.append(block_sentences)
        for sentence in block_sentences:
            if sentence not in sentences:
                sentences.append(sentence)
                if max_sentence and len(sentences) >= max_sentence:
                    return (title, sentences, passages) if passage_include else (title, sentences)
    return (title, sentences, passages) if passage_include else (title, sentences)


_sentence_punct = " \\t\\r\\n.,!?？！，。·:;()[]{}<>\"'“”‘’"


def _read_dialect():
    name = os.environ.get("KG_LANG", "한국어")
    path = os.path.join(os.path.dirname(__file__), "styles", name + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def topic_aliases(topic):
    """원문 주제와 조사 하나를 뗀 검색·매칭 별칭을 함께 돌려준다.

    원문을 버리지 않는 이유는 `호랑이`처럼 끝 글자가 조사와 같은 명사가 있기
    때문이다. `양자역학이`와 `양자역학`은 같은 묶음으로 찾되 저장 원문은 남긴다.
    """
    topic = re.sub(r"\s+", " ", (topic or "")).strip(_sentence_punct)
    if not topic:
        return []
    out = [topic]
    particles = sorted((_read_dialect().get("떼는조사") or []), key=len, reverse=True)
    for particle in particles:
        if topic.endswith(particle) and len(topic) - len(particle) >= 2:
            out.append(topic[:-len(particle)].rstrip())
            break
    return list(dict.fromkeys(x for x in out if x))


def extract_topic(g, phrase):
    """질문에서 학습·검색에 쓸 가장 작은 주제를 돌려준다.

    우선 그래프의 ``물음_`` 사례로 정형 질문의 껍데기를 벗긴다. 실제 사용자는
    ``멀미가 심한데 어떤 약을 먹으면 좋을까?``처럼 표지에 없는 자연어 질문도
    하므로, 끝에 의문 표현이 명시된 경우에만 첫 내용 낱말을 보수적인 대안으로
    쓴다. 평서문을 지식 요청으로 오인하지 않는 경계는 유지한다.
    """
    markers = []
    for n, examples in g.get("사례층", {}).items():
        if n.startswith("물음_"):
            markers.extend(examples)
    remaining, blocker = (phrase or "").strip(_sentence_punct), False
    for marker in sorted(set(markers), key=len, reverse=True):
        if not marker:
            continue
        trim_ends = remaining.strip(_sentence_punct)
        if trim_ends.startswith(marker):
            remaining = trim_ends[len(marker):]
            blocker = True
        elif trim_ends.endswith(marker):
            remaining = trim_ends[:-len(marker)]
            blocker = True
    remaining = re.sub(r"\s+", " ", remaining).strip(_sentence_punct)
    alias = topic_aliases(remaining)
    if blocker and alias:
        return remaining, alias

    # 사례층은 의도적으로 작다. 여기에 없는 말투 때문에 유효한 질문 전체가
    # 학습 불능이 되지 않도록, 언어 스타일이 선언한 질문 종결형일 때만 내용
    # 낱말을 주제로 삼는다. 언어별 종결형은 styles/*.json의 데이터이며 이
    # 함수에 한국어 표현을 추가하지 않는다.
    source_text = (phrase or "").strip()
    surface = re.sub(r"\s+", "", source_text).strip(_sentence_punct)
    species_mag_type = [re.sub(r"\s+", "", x) for x in (_read_dialect().get("학습질문종결") or []) if x]
    if not surface or not any(surface.endswith(x) for x in species_mag_type):
        return None, []
    content_words = question_word(source_text)
    if not content_words:
        return None, []
    # 물음말 자체와 지나치게 일반적인 요청 대상은 주제가 아니다. 예컨대
    # '멀미가 심한데 어떤 약…'에서는 약이 아니라 멀미를 학습·검색해야 한다.
    generic_words = set(_read_dialect().get("학습주제제외") or [])
    topic = next((word for word in content_words if word not in generic_words), None)
    alias = topic_aliases(topic)
    return (topic, alias) if alias else (None, [])


def _joined(txt):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", (txt or "")).lower()


def _alias_hits(topic, alias, txt):
    """조사를 뗀 후보가 실제 어간으로 쓰였는지 보수적으로 확인한다.

    `호랑이`에서 만든 후보 `호랑`은 본문의 `호랑이` 안에 들어 있다는 이유만으로
    별칭이 되면 안 된다. 반면 `양자역학이`의 `양자역학은`은 조사 밖에서도 실제로
    나타난 것이므로 후속 질문용 별칭으로 쓸 수 있다.
    """
    orig_topic, cand, body = _joined(topic), _joined(alias), _joined(txt)
    if not cand or cand not in body:
        return False
    if cand == orig_topic or not orig_topic.startswith(cand):
        return True
    detached = orig_topic[len(cand):]
    start = 0
    while True:
        pos = body.find(cand, start)
        if pos < 0:
            return False
        next_pos = pos + len(cand)
        if next_pos == len(body) or not detached or body[next_pos] != detached[0]:
            return True
        start = pos + 1


def _valid_aliases(topic, texts):
    cands = topic_aliases(topic)
    if not cands:
        return []
    return [a for i, a in enumerate(cands)
            if i == 0 or any(_alias_hits(topic, a, txt) for txt in texts)]


def topic_related(topic, txt):
    """검색 스니펫이 실제로 주제를 호명하는지 확인한다."""
    return any(len(_joined(a)) >= 2 and _alias_hits(topic, a, txt)
               for a in topic_aliases(topic))


def _morph():
    """`개념뽑기`가 쓰는 형태소기를 그대로 함께 쓴다. 두 벌 띄우지 않는다."""
    import build
    if build._kiwi is None:
        from kiwipiepy import Kiwi
        build._kiwi = Kiwi()
    return build._kiwi


def question_word(phrase):
    """물음에서 원문과 맞대볼 내용 낱말만 뽑는다. 없는 말은 만들지 않는다.

    `주제별칭`은 표제어 하나를 다루는 자리다. 사람이 실제로 쓰는 물음은
    표제어가 아니라 증상·상황을 늘어놓는다. 물음을 통째로 주제로 넘기면
    원문 문장 안에 그 물음이 그대로 들어 있어야 관련으로 쳐져서, 어떤
    쪽도 못 고른다 — '배가 아프고 숨이 잘 안쉬어져. 무슨 병이지' 가
    출처 0개로 떨어지던 것이 그 때문이다.

    한 글자 명사도 남긴다. `개념뽑기`가 두 글자에서 자르는 것은 코퍼스에
    노드를 세울 때 이야기이고, 여기서는 배·숨·병이 물음의 알맹이 전부일
    수 있다. 복합명사는 `개념뽑기` 가 붙여둔 것을 그대로 함께 쓴다.
    """
    phrase = str(phrase or "").strip()
    if not phrase:
        return []
    try:
        import build
        stopwords = build.stopwords
        word = [t.form for t in _morph().tokenize(phrase)
                if t.tag in ("NNG", "NNP", "SL") and t.form not in stopwords]
        word += [w for w in build.extract_concepts(phrase) if w not in word]
    except Exception:
        # 형태소기가 없는 환경에서도 조사만 뗀 낱말로 견준다.
        stopwords = set()
        word = []
        for chunk in re.findall(r"[가-힣A-Za-z]{2,}", phrase):
            word.append(chunk)
            for particle in sorted((_read_dialect().get("떼는조사") or []), key=len, reverse=True):
                if chunk.endswith(particle) and len(chunk) - len(particle) >= 1:
                    word.append(chunk[:-len(particle)])
                    break
    template = _read_dialect().get("질문틀") or []
    return [w for w in dict.fromkeys(word)
            if w and w not in stopwords and w not in template]


def word_related(words, txt, aligned_min=1):
    """물음의 내용 낱말이 이 대목에 실제로 몇 개나 나오는지로 고른다."""
    attach = _joined(txt)
    matched = sum(1 for w in dict.fromkeys(words) if _joined(w) and _joined(w) in attach)
    return matched >= max(1, int(aligned_min))


def _related_verdict(topic):
    """주제가 표제어 하나면 예전 그대로, 물음 낱말 묶음이면 겹침으로 본다.

    낱말이 여럿일 때 하나만 걸려도 통과시키면 '법'·'배' 같은 흔한 말로 딴
    문서가 딸려온다. 절반을 요구하면 한 낱말짜리 표제어 물음은 그대로
    통과하면서, 증상을 늘어놓은 물음은 그중 반은 말하는 대목만 남는다.
    """
    if isinstance(topic, (list, tuple, set, frozenset)):
        word = [w for w in dict.fromkeys(topic) if w]
        min_n = max(1, (len(word) + 1) // 2)
        return lambda sentences: bool(word) and word_related(word, " ".join(sentences), min_n)
    return lambda sentences: any(topic_related(topic, s) for s in sentences)


# ── 옆파일 ──────────────────────────────────────────────────────────────
def collect_path(kg_path):
    return os.path.splitext(kg_path)[0] + ".수집.jsonl"


_QUESTION_FRAMES = ("{주제} 알려줘", "{주제} 설명해줘", "{주제} 만드는 법",
           "{주제} 순서대로 알려줘", "{주제}가 뭐야")
# 사람이 쓴 틀이다. 주제 낱말만 갈아 끼우며, 문장을 지어내지 않는다.


def _topic_groups(records):
    """별칭이 하나라도 겹치는 기록들을 같은 주제로 묶는다."""
    group = []
    for r in records:
        cand = r.get("주제별칭") or topic_aliases(r.get("주제"))
        alias = {a for a in cand
              if a == r.get("주제") or _alias_hits(r.get("주제"), a, r.get("본문"))}
        reached = [m for m in group if m["별칭"] & alias]
        if not reached:
            group.append({"이름": r["주제"], "별칭": alias, "기록": [r]})
            continue
        base = reached[0]
        base["별칭"].update(alias)
        base["기록"].append(r)
        for other in reached[1:]:
            base["별칭"].update(other["별칭"])
            base["기록"].extend(other["기록"])
            group.remove(other)
    return group


def _is_recent(records, sec):
    if not records:
        return False
    try:
        recent = max(time.mktime(time.strptime(r["수집시각"], "%Y-%m-%dT%H:%M:%S"))
                  for r in records if r.get("수집시각"))
    except (ValueError, KeyError):
        return False
    return time.time() - recent < sec


def learn(kg_path, topic, query=None, count=10, min_source=1, force=False):
    """웹에서 주워 옆파일에 쌓는다. 원본 .kg 는 건드리지 않는다."""
    alias = topic_aliases(topic)
    if not alias:
        raise LearnFailed("학습할 주제가 비어 있습니다")
    if max_per_topic() < min_source:
        raise LearnFailed("주제당 기록 상한(%d개)이 필수 출처 수(%d곳)보다 작습니다"
                   % (max_per_topic(), min_source))
    query = query or topic
    path = collect_path(kg_path)
    existing = read_collected(path)
    existing_group = _topic_groups(existing)
    same_group = next((m for m in existing_group if set(alias) & m["별칭"]), None)
    # 검색 발췌만 저장하던 구버전 기록은 최근이어도 완성 지식으로 보지 않는다.
    # 다음 질문에서 원문을 다시 받아 `문장들`이 있는 새 기록으로 승격한다.
    done_log = same_group and [r for r in same_group["기록"]
                           if r.get("수집형식") == 3 and r.get("문장들") and r.get("대목들")]
    if done_log and not force and _is_recent(done_log, recollect_wait_sec()):
        return []
    if not same_group and len(existing_group) >= max_topic():
        raise LearnFailed("자동 학습 주제 상한(%d개)에 도달했습니다" % max_topic())
    if os.path.exists(path) and os.path.getsize(path) >= collect_max_byte():
        raise LearnFailed("수집 파일 크기 상한(%d바이트)에 도달했습니다" % collect_max_byte())

    try:
        hits = search(query, count=max(count * 2, count))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LearnFailed("웹 검색에 연결하지 못했습니다: %s" % getattr(e, "reason", e)) from e

    # 검색 발췌는 주소 후보일 뿐이다. 원문 페이지에서 완결 문장을 읽은 뒤에만
    # 지식으로 채택한다. 테스트/과거 호출의 (출처, 본문) 튜플도 완결문장 검사 후
    # 받아 하위 호환을 유지한다.
    chosen, domain = [], set()
    for item in hits:
        if isinstance(item, dict):
            url = item.get("url") or ""
            src = item.get("도메인") or urllib.parse.urlparse(url).netloc
            excerpt = item.get("발췌") or ""
            if not url or not src or src in domain or not topic_related(topic, excerpt):
                continue
            try:
                title, sentences, passages = read_source(url, topic, passage_include=True)
            except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError):
                continue
        else:
            src, txt = item
            url, title, excerpt = "", "", txt
            sentences = complete_sentences(txt, topic)
            passages = [sentences] if sentences else []
        body = " ".join(sentences)
        if (not src or src == "출처미상" or src in domain or not sentences
                or not topic_related(topic, body)):
            continue
        domain.add(src)
        chosen.append({"출처": src, "URL": url, "제목": title,
                       "검색발췌": excerpt, "문장들": sentences,
                       "대목들": passages, "본문": body})
        if len(chosen) >= count:
            break
    hits = chosen
    if len({x["출처"] for x in hits}) < min_source:
        return []
    if not hits:
        return []
    saved_aliases = _valid_aliases(topic, [x["본문"] for x in hits])
    save_topic = min(saved_aliases, key=lambda x: (len(_joined(x)), len(x))) if saved_aliases else topic
    with CollectLock(path):
        # 검색하는 동안 다른 프로세스가 썼을 수 있으므로 잠근 뒤 다시 읽는다.
        if os.path.exists(path) and os.path.getsize(path) >= collect_max_byte():
            raise LearnFailed("수집 파일 크기 상한(%d바이트)에 도달했습니다" % collect_max_byte())
        cur = read_collected(path)
        cur_groups = _topic_groups(cur)
        if not any(set(alias) & m["별칭"] for m in cur_groups) and len(cur_groups) >= max_topic():
            raise LearnFailed("자동 학습 주제 상한(%d개)에 도달했습니다" % max_topic())
        already = {r["본문"] for r in cur}
        cur_group = next((m for m in cur_groups if set(alias) & m["별칭"]), None)
        remaining_slot = max_per_topic() - len(cur_group["기록"] if cur_group else [])
        if remaining_slot <= 0:
            return []
        when = time.strftime("%Y-%m-%dT%H:%M:%S")
        cand = []
        for found in hits:
            src, txt = found["출처"], found["본문"]
            if txt in already or len(cand) >= remaining_slot:
                continue
            record = {"주제": save_topic, "주제별칭": saved_aliases, "질의": query,
                    "수집형식": 3,
                    "출처": src, "URL": found.get("URL", ""),
                    "제목": found.get("제목", ""), "본문": txt,
                    "문장들": found["문장들"], "대목들": found["대목들"],
                    "질문표현": [t.format(**{"주제": save_topic}) for t in _QUESTION_FRAMES] + [query],
                    "수집시각": when}
            line = json.dumps(record, ensure_ascii=False) + "\n"
            cand.append((record, line))

        # 검사 시점에는 상한 아래여도 이번 배치 전체를 붙이면 넘을 수 있다.
        # UTF-8 실제 바이트로 재고, 새 주제는 최소 출처 수가 다 들어갈 때만 쓴다.
        cur_size = os.path.getsize(path) if os.path.exists(path) else 0
        fresh, lines, add_size = [], [], 0
        for record, line in cand:
            byte = len(line.encode("utf-8"))
            if cur_size + add_size + byte > collect_max_byte():
                break
            fresh.append(record)
            lines.append(line)
            add_size += byte
        if not cur_group and len({r["출처"] for r in fresh}) < min_source:
            if cand and not fresh:
                raise LearnFailed("수집 파일 크기 상한 안에 새 기록을 넣을 공간이 없습니다")
            return []
        if lines:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.writelines(lines)
            except OSError as e:
                raise LearnFailed("수집 파일을 기록할 수 없습니다: %s" % e) from e
    return fresh


def save_verified_knowledge(kg_path, topic, query, sources, min_source=2):
    """승인 전에 읽고 화면에 제시한 원문 대목만 수집 파일에 저장한다.

    ``배우기``는 탐색부터 수행하는 대화형 도구다. 승인 계획에서는 이미
    검증된 대목을 다시 검색하면 계획과 다른 웹 결과를 저장할 수 있으므로,
    이 함수는 네트워크를 전혀 사용하지 않는다.
    """
    alias = topic_aliases(topic)
    if not alias:
        raise LearnFailed("학습할 주제가 비어 있습니다")
    if max_per_topic() < min_source:
        raise LearnFailed("주제당 기록 상한(%d개)이 필수 출처 수(%d곳)보다 작습니다"
                   % (max_per_topic(), min_source))
    chosen, domain = [], set()
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or source.get("URL") or "").strip()
        src = str(source.get("domain") or source.get("출처") or urllib.parse.urlparse(url).netloc).strip()
        # 승인 화면에서 본 문장이라고 해도, 그 값이 잘린 발췌가 아닌지는
        # 저장 직전에 다시 확인한다. 이 경로는 네트워크를 다시 읽지 않지만,
        # `배우기()`와 같은 완결 문장 규율을 지켜야 사실 노드가 반쪽 인용으로
        # 남지 않는다. 한 입력 항목은 정확히 한 완결 문장이어야 한다.
        sentences = []
        for value in (source.get("sentences") or source.get("문장들") or []):
            if not isinstance(value, str):
                continue
            sentence = str(value).strip()
            completed = complete_sentences(sentence, topic)
            if len(completed) == 1 and completed[0] == sanitize(sentence, max_n=1500):
                sentences.append(completed[0])
        body = " ".join(sentences)
        if not url or not src or src in domain or not sentences or not topic_related(topic, body):
            continue
        domain.add(src)
        chosen.append({"출처": src, "URL": url, "제목": str(source.get("title") or source.get("제목") or ""),
                       "문장들": sentences, "대목들": [sentences], "본문": body})
    if len(domain) < min_source:
        return []
    saved_aliases = _valid_aliases(topic, [x["본문"] for x in chosen])
    save_topic = min(saved_aliases, key=lambda x: (len(_joined(x)), len(x))) if saved_aliases else topic
    path = collect_path(kg_path)
    with CollectLock(path):
        if os.path.exists(path) and os.path.getsize(path) >= collect_max_byte():
            raise LearnFailed("수집 파일 크기 상한(%d바이트)에 도달했습니다" % collect_max_byte())
        cur = read_collected(path)
        cur_groups = _topic_groups(cur)
        cur_group = next((m for m in cur_groups if set(alias) & m["별칭"]), None)
        if not cur_group and len(cur_groups) >= max_topic():
            raise LearnFailed("자동 학습 주제 상한(%d개)에 도달했습니다" % max_topic())
        already = {r["본문"] for r in cur}
        remaining_slot = max_per_topic() - len(cur_group["기록"] if cur_group else [])
        if remaining_slot <= 0:
            return []
        when = time.strftime("%Y-%m-%dT%H:%M:%S")
        cand = []
        for found in chosen:
            if found["본문"] in already or len(cand) >= remaining_slot:
                continue
            record = {"주제": save_topic, "주제별칭": saved_aliases, "질의": query, "수집형식": 3,
                    "출처": found["출처"], "URL": found["URL"], "제목": found["제목"],
                    "본문": found["본문"], "문장들": found["문장들"], "대목들": found["대목들"],
                    "질문표현": [t.format(**{"주제": save_topic}) for t in _QUESTION_FRAMES] + [query], "수집시각": when}
            cand.append((record, json.dumps(record, ensure_ascii=False) + "\n"))
        cur_size = os.path.getsize(path) if os.path.exists(path) else 0
        fresh, lines, add_size = [], [], 0
        for record, line in cand:
            byte = len(line.encode("utf-8"))
            if cur_size + add_size + byte > collect_max_byte():
                break
            fresh.append(record); lines.append(line); add_size += byte
        if not cur_group and len({r["출처"] for r in fresh}) < min_source:
            return []
        if lines:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.writelines(lines)
            except OSError as e:
                raise LearnFailed("수집 파일을 기록할 수 없습니다: %s" % e) from e
    return fresh


def read_collected(path):
    out = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get("주제") and d.get("본문"):
                        out.append(d)
                except ValueError:
                    pass
    return out


def stack_on(g, records):
    """수집 기록을 그래프에 붙인다. 노드 이름은 전부 접두사로 표시해 둔다 —
    어느 것이 기계가 주워온 것인지 그래프만 보고도 알 수 있어야 한다."""
    g["_주제별칭"] = {}
    g["_주제사실"] = {}
    g["_주제대목"] = {}
    # 발췌만 있던 구버전 기록은 감사 로그로 남기되 지식 그래프에는 얹지 않는다.
    # 원문에서 가져온 완결 문장 목록이 있는 기록만 사실 노드가 된다.
    adopted = [r for r in records if r.get("수집형식") == 3 and r.get("문장들") and r.get("대목들")
          and any(topic_related(r.get("주제"), s) for s in r["문장들"])]
    for group in _topic_groups(adopted):
        topic, rs = group["이름"], group["기록"]
        claim = "지식_" + topic
        sentence_before_sub = [s for r in rs for s in r.get("문장들", [])]
        sentence_before_sub = list(dict.fromkeys(sentence_before_sub))
        g["_주제별칭"][claim] = sorted(_valid_aliases(topic, sentence_before_sub), key=len, reverse=True)
        # 주제 루트와 각 사실을 나눠야 그래프가 실제로 무엇을 배웠는지 보인다.
        g["공통층"][claim] = list(dict.fromkeys([topic] + [q for r in rs for q in r.get("질문표현", [])]))
        g["_주제사실"][claim] = []
        g["_주제대목"][claim] = []

        domain = sorted({r["출처"] for r in rs})
        g.setdefault("출처", {})[claim] = "웹 %d곳 · %s%s" % (
            len(domain), ", ".join(domain[:2]), " 외" if len(domain) > 2 else "")

        fact_num, source_group = {}, {}
        for r in rs:
            source_group.setdefault(r["출처"], []).append(r)
        for i, (src, logs_source) in enumerate(sorted(source_group.items()), 1):
            rep = logs_source[-1]
            source_node = "출처_%s_%d" % (topic, i)
            g["사례층"][source_node] = [rep.get("제목") or src]
            g["출처"][source_node] = rep.get("URL") or src
            if source_node not in g.setdefault("증거", []):
                g["증거"].append(source_node)
            for r in logs_source:
                for passage in r.get("대목들", []):
                    if passage:
                        g["_주제대목"][claim].append({"출처": src,
                                                    "문장들": list(passage)})
                for sentence in r.get("문장들", []):
                    if sentence not in fact_num:
                        fact_num[sentence] = len(fact_num) + 1
                        fact = "지식_%s_사실_%d" % (topic, fact_num[sentence])
                        g["공통층"][fact] = [sentence]
                        g["출처"][fact] = r.get("URL") or r["출처"]
                        g["_주제사실"][claim].append(fact)
                        g["엣지"].append([fact, "충족", claim])
                    else:
                        fact = "지식_%s_사실_%d" % (topic, fact_num[sentence])
                    edge = [source_node, "증명", fact]
                    if edge not in g["엣지"]:
                        g["엣지"].append(edge)

        g["엣지"].append([claim, "충족", g["목표"]])
    return g


def load(kg_path):
    """engine.load() 를 그대로 쓰되 파싱 직후에 수집분을 얹는다.

    load() 뒤쪽(학습 덧칠·검증·관련개념·벡터)을 여기로 복사하면 engine 이
    바뀔 때 조용히 어긋난다. 파싱 함수만 잠깐 감싸서 나머지를 전부 물려받는다."""
    orig = eng.read_kg
    record = read_collected(collect_path(kg_path))

    def overlay(path):
        return stack_on(orig(path), record)

    eng.read_kg = overlay
    try:
        return eng.load(kg_path)
    finally:
        eng.read_kg = orig


def ask(g, phrase):
    """→ (아는 주제인가, 답).

    주제는 원문에서 확인된 별칭으로 정확히 고르고, 답은 그 주제 아래의 완결
    사실 노드 가운데 질문과 가까운 것 최대 여섯 개를 고른다. 잘린 발췌의 끝을
    지어내지 않고 원문 문장을 문단으로 조립한다.

    모르는 주제에 대고 억지로 대답하지 않는다. '무관하다'가 아니라
    '아직 모른다'로 답한다."""
    topic_table = []
    for n, alias in (g.get("_주제별칭") or {}).items():
        topic_table.extend((a, n) for a in alias)
    blocker = next(((a, n) for a, n in sorted(topic_table, key=lambda x: len(x[0]), reverse=True)
                if a and a in phrase), None)
    if not blocker:
        unknown = ((g.get("공통층") or {}).get("상태_지식부족")
                or (g.get("무관층") or {}).get("_타죄명:상태_지식부족")
                or ["아직 그 내용을 모릅니다"])
        return False, unknown[0]

    caught_topic, claim = blocker
    facts = (g.get("_주제사실") or {}).get(claim, [])
    if not facts:
        return False, "아직 원문에서 완결된 지식을 만들지 못했습니다."
    passages = (g.get("_주제대목") or {}).get(claim, [])
    basis = _vec(phrase)
    cand = []
    for order, item in enumerate(passages):
        text = " ".join(item.get("문장들") or [])
        if not text or "..." in text or "…" in text:
            continue
        score = float((_vec(text) @ basis).max())
        cand.append((score, order, item.get("출처"), text))
    if cand:
        cand.sort(reverse=True)
        best = cand[0][0]
        request_enumerate = any(x in phrase for x in ("목록", "장점", "단점", "단계", "순서", "종류", "이유"))
        enumerate_start = re.compile(r"^(첫째|둘째|셋째|넷째|다섯째|먼저|다음으로|마지막으로|\d+[.)])")
        ans, body, by_source = [], set(), {}
        # 고정 '6문장'이 아니라 최고 대목과 의미상 가까운 완결 문단을 고른다.
        # 12k 안전망에서도 문단 중간은 자르지 않는다.
        for score, order, source, text in cand:
            if score < max(0.18, best - 0.10) or text in body:
                continue
            if not request_enumerate and enumerate_start.match(text):
                continue
            if sum(len(x) for x in ans) + len(text) > 12000:
                continue
            # 한 출처의 반복 서술이 답을 독점하지 않게 하되 원문 다양성은 유지한다.
            if by_source.get(source, 0) >= 3:
                continue
            body.add(text)
            by_source[source] = by_source.get(source, 0) + 1
            ans.append((order, text))
        if ans:
            # 같은 점수권 안에서는 원문 순서가 담화 연결을 보존한다.
            return True, "\n\n".join(text for _order, text in sorted(ans))

    # 구버전/예외 그래프의 대목 정보가 없을 때도 완결 사실만 반환한다.
    row = [g["공통층"][n][0] for n in facts if g["공통층"].get(n)]
    return True, "\n\n".join(x for x in row if "..." not in x and "…" not in x)


# ── CLI ─────────────────────────────────────────────────────────────────
def _usage():
    print(__doc__.strip())
    print("""
사용법
  python web_learn.py --배우다 <주제> [--질의 "검색어"] [--개수 10] [--새로고침]
  python web_learn.py --묻다   <말>
  python web_learn.py --보기
  python web_learn.py --check

  --그래프 <경로>   기본 graphs/graph_자가학습.kg""")


def _main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        return _usage()

    def value(name, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    kg = value("--그래프", "graphs/graph_자가학습.kg")

    if "--check" in argv:
        return _selfcheck(kg)

    if "--보기" in argv:
        record = read_collected(collect_path(kg))
        adopted = [r for r in record if topic_related(r.get("주제"), r.get("본문"))]
        exclude = [r for r in record if r not in adopted]
        groups = _topic_groups(adopted)
        print("수집 파일: %s  (기록 %d개, 채택 %d개, 제외 %d개, 주제 %d개)"
              % (collect_path(kg), len(record), len(adopted), len(exclude), len(groups)))
        for group in groups:
            topic, rs = group["이름"], group["기록"]
            print("\n[%s] 출처 %d곳" % (topic, len({r["출처"] for r in rs})))
            for r in rs:
                print("   · %-24s %s" % (r["출처"][:24], r["본문"][:56]))
        if exclude:
            print("\n[품질 필터로 제외 — 원본 감사 로그에는 보존]")
            for r in exclude:
                print("   · %-12s %-24s %s"
                      % (r["주제"][:12], r.get("출처", "")[:24], r["본문"][:56]))
        return

    if "--배우다" in argv:
        topic = value("--배우다")
        query = value("--질의", topic)
        try:
            fresh = learn(kg, topic, query, int(value("--개수", "10")),
                         force="--새로고침" in argv)
        except LearnFailed as e:
            print("[학습 실패] %s" % e)
            return 1
        print("'%s' 검색 → 새로 %d건 수집 (옆파일: %s)" % (query, len(fresh), collect_path(kg)))
        for r in fresh:
            print("   · %-24s %s" % (r["출처"][:24], r["본문"][:56]))
        if not fresh:
            print("   (이미 갖고 있는 내용이거나 검색 결과가 없다)")
        return

    if "--묻다" in argv:
        g = load(kg)
        phrase = value("--묻다")
        knows, ans = ask(g, phrase)
        learn_tries = False
        if not knows:
            extracted_topic, _alias = extract_topic(g, phrase)
            if extracted_topic:
                learn_tries = True
                failure_stmt_phrase = None
                print("[자동학습] 그래프 표지를 이용해 '%s' 주제를 추출했습니다. 스스로 배웁니다..."
                      % extracted_topic)
                try:
                    fresh = learn(kg, extracted_topic, phrase, int(value("--개수", "10")), min_source=2)
                except LearnFailed as e:
                    failure_stmt_phrase = str(e)
                    fresh = []
                if fresh:
                    g = load(kg)
                    knows, ans = ask(g, phrase)
                elif not knows:
                    ans = (("자동 학습을 완료하지 못했습니다: " + failure_stmt_phrase) if failure_stmt_phrase else
                           "서로 다른 출처 두 곳에서 주제를 확인하지 못해 지식으로 채택하지 않았습니다.")

        print(ans)
        if not knows:
            print("   (배우려면: python web_learn.py --배우다 <주제>)")
        return 1 if learn_tries and not knows else 0

    _usage()


def _selfcheck(kg):
    problem = []
    t = "재료 준비 | 조리 # 완성\n두 번째 줄"
    s = sanitize(t, kg_safe=True)
    if "\n" in s or "|" in s or "#" in s:
        problem.append("살균이 개행/구분자를 남긴다: %r" % s)
    if sanitize("<b>가</b>격은 3000원 # 별도")[:2] != "가격":
        problem.append("태그 제거 실패")
    test_sentence = complete_sentences("양자역학은 설명 도중 잘린 내용입니다... "
                         "양자역학은 미시 세계를 설명하는 물리 이론입니다.", "양자역학")
    if test_sentence != ["양자역학은 미시 세계를 설명하는 물리 이론입니다."]:
        problem.append("잘린 발췌를 버리고 완결 문장만 고르지 못한다: %r" % test_sentence)
    g = load(kg)
    if not g.get("공통층"):
        problem.append("그래프가 비었다")
    for n in (g.get("출처") or {}):
        if n not in g["공통층"] and n not in g["사례층"] and n not in g.get("무관층", {}):
            problem.append("출처가 붙은 '%s' 이 어느 층에도 없다" % n)
    topic, alias = extract_topic(g, "양자역학이 뭐야")
    if topic != "양자역학이" or "양자역학" not in alias:
        problem.append("조사 별칭 추출 실패: %r %r" % (topic, alias))
    if extract_topic(g, "초전도체란")[0] != "초전도체":
        problem.append("'~란' 질문에서 주제를 못 뽑는다")
    if extract_topic(g, "폴란드가 뭐야")[0] != "폴란드가":
        problem.append("주제 내부의 질문 표지 글자를 지운다")
    if extract_topic(g, "뭐야")[0] is not None:
        problem.append("표지만 있는 질문에서 빈 주제를 학습한다")
    if not topic_related("양자역학이", "양자역학은 물리학의 이론 체계다"):
        problem.append("조사 변형이 있는 관련 스니펫을 버린다")
    if topic_related("양자역학이", "양자컴퓨터는 0과 1을 동시에 사용한다"):
        problem.append("주제를 직접 말하지 않은 스니펫을 채택한다")
    if "호랑" in _valid_aliases("호랑이", ["호랑이는 고양잇과 동물이다"]):
        problem.append("명사 끝 글자를 조사로 오인해 거짓 별칭을 만든다")
    if "양자역학" not in _valid_aliases("양자역학이", ["양자역학은 물리 이론이다"]):
        problem.append("본문으로 확인된 조사 제거 별칭을 버린다")

    # 서로 다른 표면형도 별칭이 겹치면 한 주제다.
    log_test = [
        {"주제": "양자역학이", "본문": "양자역학은 미시 세계의 이론이다.",
         "수집형식": 3, "문장들": ["양자역학은 미시 세계의 이론이다."],
         "대목들": [["양자역학은 미시 세계의 이론이다."]], "출처": "a",
         "주제별칭": ["양자역학이", "양자역학"]},
        {"주제": "양자역학", "본문": "양자역학의 측정에는 고유한 규칙이 있다.",
         "수집형식": 3, "문장들": ["양자역학의 측정에는 고유한 규칙이 있다."],
         "대목들": [["양자역학의 측정에는 고유한 규칙이 있다."]], "출처": "b",
         "주제별칭": ["양자역학"]},
    ]
    if len(_topic_groups(log_test)) != 1:
        problem.append("조사만 다른 주제가 중복 묶음으로 남는다")
    test_graph = {"공통층": {}, "사례층": {}, "무관층": {}, "엣지": [],
                  "출처": {}, "목표": "목표"}
    log_same_source = log_test + [
        {"주제": "양자역학", "본문": "양자역학은 파동 함수를 사용한다.",
         "수집형식": 3, "문장들": ["양자역학은 파동 함수를 사용한다."],
         "대목들": [["양자역학은 파동 함수를 사용한다."]], "출처": "a",
         "주제별칭": ["양자역학"]},
        {"주제": "양자역학", "본문": "양자컴퓨터는 중첩을 계산에 쓴다.",
         "수집형식": 3, "문장들": ["양자컴퓨터는 중첩을 계산에 쓴다."],
         "대목들": [["양자컴퓨터는 중첩을 계산에 쓴다."]], "출처": "c",
         "주제별칭": ["양자역학"]},
    ]
    stack_on(test_graph, log_same_source)
    proof_count = len([e for e in test_graph["엣지"] if e[1] == "증명"])
    source_node_count = len([n for n in test_graph["사례층"] if n.startswith("출처_")])
    if source_node_count != 2 or proof_count != 3:
        problem.append("출처와 완결 사실 노드 구성이 틀렸다: 출처 %d, 증명 %d"
                   % (source_node_count, proof_count))
    if any("양자컴퓨터" in s for v in test_graph["사례층"].values() for s in v):
        problem.append("과거 로그의 무관 스니펫을 런타임 지식으로 얹는다")

    # 네트워크 대신 고정 검색 결과를 넣어 저장·품질 필터·재수집 방지를 함께 잰다.
    import tempfile
    orig_search = globals()["search"]
    try:
        with tempfile.TemporaryDirectory(prefix="web-learn-check-") as td:
            test_kg = os.path.join(td, "시험.kg")
            globals()["search"] = lambda _q, count=10: [
                ("a.example", "양자역학은 미시 세계를 설명하는 물리학의 이론 체계입니다."),
                ("b.example", "양자역학의 상태와 측정은 고전 역학과 다른 규칙을 따릅니다."),
                ("c.example", "양자컴퓨터는 0과 1을 동시에 사용해 계산할 수 있습니다."),
            ]
            fresh = learn(test_kg, "양자역학이", "양자역학이 뭐야", 3, min_source=2)
            if len(fresh) != 2 or any(r["출처"] == "c.example" for r in fresh):
                problem.append("검색 품질 필터가 무관 스니펫을 거르지 못한다: %r" % fresh)
            if any(r["주제"] != "양자역학" or r.get("수집형식") != 3 for r in fresh):
                problem.append("검증된 조사 제거형을 대표 주제로 저장하지 못한다: %r" % fresh)
            if learn(test_kg, "양자역학", "양자역학 설명해줘", 3, min_source=2):
                problem.append("같은 주제를 조사만 바꿔 즉시 중복 수집한다")

            # 운영 상한과 잠금도 실제 파일 경계에서 잰다.
            env_name = ("KG_LEARN_MAX_TOPICS", "KG_LEARN_MAX_RECORDS",
                    "KG_LEARN_MAX_BYTES", "KG_LEARN_COOLDOWN")
            orig_env = {k: os.environ.get(k) for k in env_name}
            try:
                globals()["search"] = lambda q, count=10: [
                    ("a.example", "%s에 관한 첫 번째 독립 출처의 충분히 긴 설명입니다." % q),
                    ("b.example", "%s에 관한 두 번째 독립 출처의 충분히 긴 설명입니다." % q),
                    ("c.example", "%s에 관한 세 번째 독립 출처의 충분히 긴 설명입니다." % q),
                ]
                os.environ["KG_LEARN_MAX_RECORDS"] = "2"
                limit_kg = os.path.join(td, "제한.kg")
                log_limit = learn(limit_kg, "별하나", "별하나", 3, min_source=2)
                if len(log_limit) != 2 or len(read_collected(collect_path(limit_kg))) != 2:
                    problem.append("주제당 기록 상한을 넘거나 덜 기록한다")

                os.environ["KG_LEARN_MAX_TOPICS"] = "1"
                try:
                    learn(limit_kg, "별둘", "별둘", 2, min_source=2)
                    problem.append("전체 주제 상한을 넘겨 새 주제를 기록한다")
                except LearnFailed:
                    pass

                lock_kg = os.path.join(td, "잠금.kg")
                lock_file = collect_path(lock_kg) + ".lock"
                with open(lock_file, "w", encoding="ascii") as f:
                    f.write("testing\n")
                try:
                    learn(lock_kg, "잠금시험", "잠금시험", 2, min_source=2)
                    problem.append("동시 수집 잠금을 무시하고 기록한다")
                except LearnFailed:
                    pass
                finally:
                    try:
                        os.unlink(lock_file)
                    except FileNotFoundError:
                        pass

                os.environ["KG_LEARN_MAX_BYTES"] = "100"
                small_kg = os.path.join(td, "작은.kg")
                try:
                    learn(small_kg, "크기시험", "크기시험", 2, min_source=2)
                    problem.append("배치 쓰기로 파일 크기 상한을 넘긴다")
                except LearnFailed:
                    pass
                if os.path.exists(collect_path(small_kg)):
                    problem.append("크기 상한에 걸린 불완전 배치를 일부 기록한다")

                os.environ["KG_LEARN_MAX_RECORDS"] = "1"
                try:
                    learn(os.path.join(td, "설정오류.kg"), "설정오류", "설정오류",
                         2, min_source=2)
                    problem.append("필수 출처보다 작은 기록 상한을 허용한다")
                except LearnFailed:
                    pass
            finally:
                for k, v in orig_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            def cutoff(_q, count=10):
                raise urllib.error.URLError("offline")
            globals()["search"] = cutoff
            try:
                learn(os.path.join(td, "오프라인.kg"), "초전도체", "초전도체란", 3)
                problem.append("네트워크 실패를 성공으로 처리한다")
            except LearnFailed:
                pass
    finally:
        globals()["search"] = orig_search
    print("자체검사: %s" % ("통과" if not problem else "%d건 실패" % len(problem)))
    for x in problem:
        print("   - " + x)
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(_main() or 0)
