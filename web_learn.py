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
def _환경정수(이름, 기본, 최소=1):
    try:
        return max(int(os.environ.get(이름, 기본)), 최소)
    except (TypeError, ValueError):
        return 기본


최대주제 = lambda: _환경정수("KG_LEARN_MAX_TOPICS", 200)
주제당최대 = lambda: _환경정수("KG_LEARN_MAX_RECORDS", 20)
수집최대바이트 = lambda: _환경정수("KG_LEARN_MAX_BYTES", 5 * 1024 * 1024)
재수집대기초 = lambda: _환경정수("KG_LEARN_COOLDOWN", 300)


class 학습실패(RuntimeError):
    pass


class 수집잠금:
    """동시에 같은 JSONL을 쓰지 못하게 하는 작은 파일 잠금."""
    def __init__(self, 경로):
        self.경로 = 경로 + ".lock"
        self.fd = None

    def __enter__(self):
        for 회 in range(2):
            try:
                self.fd = os.open(self.경로, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, ("%d %d\n" % (os.getpid(), int(time.time()))).encode("ascii"))
                return self
            except FileExistsError as e:
                try:
                    오래됨 = time.time() - os.path.getmtime(self.경로) > 120
                except FileNotFoundError:
                    continue
                if 오래됨 and 회 == 0:
                    try:
                        os.unlink(self.경로)
                    except FileNotFoundError:
                        pass
                    continue
                raise 학습실패("같은 지식 파일을 다른 학습 작업이 갱신 중입니다") from e
            except OSError as e:
                if self.fd is not None:
                    os.close(self.fd)
                    self.fd = None
                raise 학습실패("수집 잠금 파일을 만들 수 없습니다: %s" % e) from e

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.unlink(self.경로)
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
_제어 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_태그 = re.compile(r"<[^>]+>")


def 살균(글, 최대=700, kg안전=False):
    """주워온 문자열을 노드 예시로 쓸 수 있는 한 줄로 만든다."""
    # 태그는 공백이 아니라 빈 문자열로 지운다. 검색 스니펫은 질의어를 굵게
    # 표시하는데, <b>가</b>격은 처럼 낱말 중간에 걸리면 공백 치환이 낱말을 쪼갠다.
    글 = html.unescape(_태그.sub("", 글 or ""))
    글 = _제어.sub(" ", 글)
    글 = re.sub(r"\s+", " ", 글).strip().strip('"').strip()
    if kg안전:
        # .kg 한 줄로 나갈 때만. 뜻을 해치지 않는 최소 치환.
        글 = 글.replace("|", "／").replace("#", "＃")
    return 글[:최대].strip()


def kg줄(이름, 문장들, 출처=None):
    """노드 하나를 .kg 한 줄로. 내보내기용이며 평소 경로에는 쓰이지 않는다."""
    머리 = 이름 + ("@" + 출처 if 출처 else "")
    return '%s: %s' % (머리, " | ".join('"%s"' % 살균(s, kg안전=True) for s in 문장들))


# ── 검색 ────────────────────────────────────────────────────────────────
_링크 = re.compile(r"href=\"(https?://[^\"]+)\"[^>]*class='result-link'", re.I)
_스니펫 = re.compile(r"class='result-snippet'[^>]*>(.*?)</td>", re.DOTALL | re.I)


def _실제주소(url):
    """DuckDuckGo 우회 링크면 원문 주소를 꺼낸다."""
    p = urllib.parse.urlparse(html.unescape(url))
    if "duckduckgo.com" in p.netloc:
        q = urllib.parse.parse_qs(p.query)
        if q.get("uddg"):
            return q["uddg"][0]
    return urllib.parse.urlunparse(p)


def 검색(질의, 개수=10, 최소길이=40):
    """열린 웹 검색. 원문 URL과 검색 발췌를 돌려준다.

    발췌는 관련 결과를 거르는 힌트일 뿐 지식으로 저장하지 않는다. 여러 URL을
    받아야 원문 교차검증이 가능해지므로 기본값을 10 으로 둔다."""
    req = urllib.request.Request(
        "https://lite.duckduckgo.com/lite/",
        data=urllib.parse.urlencode({"q": 질의}).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        본문 = r.read().decode("utf-8", "replace")

    링크 = [_실제주소(u) for u in _링크.findall(본문)]
    조각 = [살균(s) for s in _스니펫.findall(본문)]
    out, 본것 = [], set()
    for i, 글 in enumerate(조각):
        if len(글) < 최소길이 or 글 in 본것:
            continue                       # 너무 짧은 것은 근거가 못 된다
        본것.add(글)
        url = 링크[i] if i < len(링크) else ""
        if not url:
            continue
        out.append({"url": url, "도메인": urllib.parse.urlparse(url).netloc,
                    "발췌": 글})
        if len(out) >= 개수:
            break
    return out


class _본문추출기(HTMLParser):
    """광고·메뉴·스크립트를 빼고 문서 본문 블록만 모은다."""
    블록태그 = {"p", "article", "section", "main", "h1", "h2", "h3", "li", "blockquote"}
    버릴태그 = {"script", "style", "noscript", "svg", "canvas", "nav", "footer", "header", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.버림 = 0
        self.블록 = []
        self.현재 = []

    def handle_starttag(self, tag, _attrs):
        tag = tag.lower()
        if tag in self.버릴태그:
            self.버림 += 1
        elif not self.버림 and tag in self.블록태그 and self.현재:
            self._닫기()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.버릴태그:
            self.버림 = max(0, self.버림 - 1)
        elif not self.버림 and tag in self.블록태그:
            self._닫기()

    def handle_data(self, data):
        if not self.버림:
            self.현재.append(data)

    def _닫기(self):
        글 = 살균(" ".join(self.현재), 최대=12000)
        if len(글) >= 30:
            self.블록.append(글)
        self.현재 = []

    def 끝내기(self):
        self._닫기()
        return list(dict.fromkeys(self.블록))


_문장 = re.compile(r"[^.!?。！？\n]{12,}[.!?。！？](?=\s|$)")


def 완결문장들(글, 주제=None, 최대문장=None):
    """원문 블록의 완결 문장을 순서대로 고른다. 주제가 있으면 관련 문장만 고른다."""
    out = []
    for m in _문장.finditer(글 or ""):
        문장 = 살균(m.group(0), 최대=1500)
        if (문장.endswith("...") or 문장.endswith("…")
                or (주제 and not 주제관련(주제, 문장))
                or 문장 in out):
            continue
        out.append(문장)
        if 최대문장 and len(out) >= 최대문장:
            break
    return out


def 원문읽기(url, 주제, 최대바이트=2 * 1024 * 1024, 최대문장=None, 대목포함=False):
    """웹 페이지 원문을 읽어 (제목, 완결 지식 문장들)을 돌려준다."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(최대바이트 + 1)
        if len(raw) > 최대바이트:
            raw = raw[:최대바이트]
        charset = r.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, "replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = 살균(title_match.group(1), 최대=300) if title_match else ""
    parser = _본문추출기()
    parser.feed(text)
    sentences, passages = [], []
    for block in parser.끝내기():
        block_sentences = 완결문장들(block)
        # 주제를 말하는 문장이 하나라도 있는 문단은 대명사·후속 설명까지 모두
        # 같은 지식 대목이다. 문장마다 주제 낱말을 반복하도록 요구하면 맥락이 잘린다.
        if not block_sentences or not any(주제관련(주제, s) for s in block_sentences):
            continue
        passages.append(block_sentences)
        for sentence in block_sentences:
            if sentence not in sentences:
                sentences.append(sentence)
                if 최대문장 and len(sentences) >= 최대문장:
                    return (title, sentences, passages) if 대목포함 else (title, sentences)
    return (title, sentences, passages) if 대목포함 else (title, sentences)


_끝문장부호 = " \\t\\r\\n.,!?？！，。·:;()[]{}<>\"'“”‘’"


def _말투읽기():
    이름 = os.environ.get("KG_LANG", "한국어")
    경로 = os.path.join(os.path.dirname(__file__), "styles", 이름 + ".json")
    try:
        with open(경로, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def 주제별칭(주제):
    """원문 주제와 조사 하나를 뗀 검색·매칭 별칭을 함께 돌려준다.

    원문을 버리지 않는 이유는 `호랑이`처럼 끝 글자가 조사와 같은 명사가 있기
    때문이다. `양자역학이`와 `양자역학`은 같은 묶음으로 찾되 저장 원문은 남긴다.
    """
    주제 = re.sub(r"\s+", " ", (주제 or "")).strip(_끝문장부호)
    if not 주제:
        return []
    out = [주제]
    조사들 = sorted((_말투읽기().get("떼는조사") or []), key=len, reverse=True)
    for 조사 in 조사들:
        if 주제.endswith(조사) and len(주제) - len(조사) >= 2:
            out.append(주제[:-len(조사)].rstrip())
            break
    return list(dict.fromkeys(x for x in out if x))


def 주제추출(g, 말):
    """그래프의 `물음_` 사례만 이용해 질문 껍데기를 벗긴다.

    → (원문주제, 별칭들) 또는 (None, []). 표지가 없는 평서문을 지식 요청으로
    오인하지 않는다. 새 질문형은 파이썬이 아니라 graph_자가학습.kg에 더한다.
    """
    표지들 = []
    for n, 예시들 in g.get("사례층", {}).items():
        if n.startswith("물음_"):
            표지들.extend(예시들)
    남음, 걸림 = (말 or "").strip(_끝문장부호), False
    for 표지 in sorted(set(표지들), key=len, reverse=True):
        if not 표지:
            continue
        앞뒤뺌 = 남음.strip(_끝문장부호)
        if 앞뒤뺌.startswith(표지):
            남음 = 앞뒤뺌[len(표지):]
            걸림 = True
        elif 앞뒤뺌.endswith(표지):
            남음 = 앞뒤뺌[:-len(표지)]
            걸림 = True
    남음 = re.sub(r"\s+", " ", 남음).strip(_끝문장부호)
    별칭 = 주제별칭(남음)
    return (남음, 별칭) if 걸림 and 별칭 else (None, [])


def _붙인글(글):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", (글 or "")).lower()


def _별칭등장(주제, 별칭, 글):
    """조사를 뗀 후보가 실제 어간으로 쓰였는지 보수적으로 확인한다.

    `호랑이`에서 만든 후보 `호랑`은 본문의 `호랑이` 안에 들어 있다는 이유만으로
    별칭이 되면 안 된다. 반면 `양자역학이`의 `양자역학은`은 조사 밖에서도 실제로
    나타난 것이므로 후속 질문용 별칭으로 쓸 수 있다.
    """
    원주제, 후보, 본문 = _붙인글(주제), _붙인글(별칭), _붙인글(글)
    if not 후보 or 후보 not in 본문:
        return False
    if 후보 == 원주제 or not 원주제.startswith(후보):
        return True
    뗀부분 = 원주제[len(후보):]
    시작 = 0
    while True:
        자리 = 본문.find(후보, 시작)
        if 자리 < 0:
            return False
        다음자리 = 자리 + len(후보)
        if 다음자리 == len(본문) or not 뗀부분 or 본문[다음자리] != 뗀부분[0]:
            return True
        시작 = 자리 + 1


def _유효별칭(주제, 글들):
    후보들 = 주제별칭(주제)
    if not 후보들:
        return []
    return [a for i, a in enumerate(후보들)
            if i == 0 or any(_별칭등장(주제, a, 글) for 글 in 글들)]


def 주제관련(주제, 글):
    """검색 스니펫이 실제로 주제를 호명하는지 확인한다."""
    return any(len(_붙인글(a)) >= 2 and _별칭등장(주제, a, 글)
               for a in 주제별칭(주제))


# ── 옆파일 ──────────────────────────────────────────────────────────────
def 수집경로(kg경로):
    return os.path.splitext(kg경로)[0] + ".수집.jsonl"


_질문틀 = ("{주제} 알려줘", "{주제} 설명해줘", "{주제} 만드는 법",
           "{주제} 순서대로 알려줘", "{주제}가 뭐야")
# 사람이 쓴 틀이다. 주제 낱말만 갈아 끼우며, 문장을 지어내지 않는다.


def _주제묶음(기록들):
    """별칭이 하나라도 겹치는 기록들을 같은 주제로 묶는다."""
    묶음 = []
    for r in 기록들:
        후보 = r.get("주제별칭") or 주제별칭(r.get("주제"))
        별칭 = {a for a in 후보
              if a == r.get("주제") or _별칭등장(r.get("주제"), a, r.get("본문"))}
        닿은 = [m for m in 묶음 if m["별칭"] & 별칭]
        if not 닿은:
            묶음.append({"이름": r["주제"], "별칭": 별칭, "기록": [r]})
            continue
        바탕 = 닿은[0]
        바탕["별칭"].update(별칭)
        바탕["기록"].append(r)
        for 다른 in 닿은[1:]:
            바탕["별칭"].update(다른["별칭"])
            바탕["기록"].extend(다른["기록"])
            묶음.remove(다른)
    return 묶음


def _최근인가(기록들, 초):
    if not 기록들:
        return False
    try:
        최근 = max(time.mktime(time.strptime(r["수집시각"], "%Y-%m-%dT%H:%M:%S"))
                  for r in 기록들 if r.get("수집시각"))
    except (ValueError, KeyError):
        return False
    return time.time() - 최근 < 초


def 배우기(kg경로, 주제, 질의=None, 개수=10, 최소출처=1, 강제=False):
    """웹에서 주워 옆파일에 쌓는다. 원본 .kg 는 건드리지 않는다."""
    별칭 = 주제별칭(주제)
    if not 별칭:
        raise 학습실패("학습할 주제가 비어 있습니다")
    if 주제당최대() < 최소출처:
        raise 학습실패("주제당 기록 상한(%d개)이 필수 출처 수(%d곳)보다 작습니다"
                   % (주제당최대(), 최소출처))
    질의 = 질의 or 주제
    경로 = 수집경로(kg경로)
    기존 = 수집읽기(경로)
    기존묶음 = _주제묶음(기존)
    같은묶음 = next((m for m in 기존묶음 if set(별칭) & m["별칭"]), None)
    # 검색 발췌만 저장하던 구버전 기록은 최근이어도 완성 지식으로 보지 않는다.
    # 다음 질문에서 원문을 다시 받아 `문장들`이 있는 새 기록으로 승격한다.
    완성기록 = 같은묶음 and [r for r in 같은묶음["기록"]
                           if r.get("수집형식") == 3 and r.get("문장들") and r.get("대목들")]
    if 완성기록 and not 강제 and _최근인가(완성기록, 재수집대기초()):
        return []
    if not 같은묶음 and len(기존묶음) >= 최대주제():
        raise 학습실패("자동 학습 주제 상한(%d개)에 도달했습니다" % 최대주제())
    if os.path.exists(경로) and os.path.getsize(경로) >= 수집최대바이트():
        raise 학습실패("수집 파일 크기 상한(%d바이트)에 도달했습니다" % 수집최대바이트())

    try:
        찾은 = 검색(질의, 개수=max(개수 * 2, 개수))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise 학습실패("웹 검색에 연결하지 못했습니다: %s" % getattr(e, "reason", e)) from e

    # 검색 발췌는 주소 후보일 뿐이다. 원문 페이지에서 완결 문장을 읽은 뒤에만
    # 지식으로 채택한다. 테스트/과거 호출의 (출처, 본문) 튜플도 완결문장 검사 후
    # 받아 하위 호환을 유지한다.
    고른것, 도메인 = [], set()
    for item in 찾은:
        if isinstance(item, dict):
            url = item.get("url") or ""
            출처 = item.get("도메인") or urllib.parse.urlparse(url).netloc
            발췌 = item.get("발췌") or ""
            if not url or not 출처 or 출처 in 도메인 or not 주제관련(주제, 발췌):
                continue
            try:
                제목, 문장들, 대목들 = 원문읽기(url, 주제, 대목포함=True)
            except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError):
                continue
        else:
            출처, 글 = item
            url, 제목, 발췌 = "", "", 글
            문장들 = 완결문장들(글, 주제)
            대목들 = [문장들] if 문장들 else []
        본문 = " ".join(문장들)
        if (not 출처 or 출처 == "출처미상" or 출처 in 도메인 or not 문장들
                or not 주제관련(주제, 본문)):
            continue
        도메인.add(출처)
        고른것.append({"출처": 출처, "URL": url, "제목": 제목,
                       "검색발췌": 발췌, "문장들": 문장들,
                       "대목들": 대목들, "본문": 본문})
        if len(고른것) >= 개수:
            break
    찾은 = 고른것
    if len({x["출처"] for x in 찾은}) < 최소출처:
        return []
    if not 찾은:
        return []
    저장별칭 = _유효별칭(주제, [x["본문"] for x in 찾은])
    저장주제 = min(저장별칭, key=lambda x: (len(_붙인글(x)), len(x))) if 저장별칭 else 주제
    with 수집잠금(경로):
        # 검색하는 동안 다른 프로세스가 썼을 수 있으므로 잠근 뒤 다시 읽는다.
        if os.path.exists(경로) and os.path.getsize(경로) >= 수집최대바이트():
            raise 학습실패("수집 파일 크기 상한(%d바이트)에 도달했습니다" % 수집최대바이트())
        현재 = 수집읽기(경로)
        현재묶음들 = _주제묶음(현재)
        if not any(set(별칭) & m["별칭"] for m in 현재묶음들) and len(현재묶음들) >= 최대주제():
            raise 학습실패("자동 학습 주제 상한(%d개)에 도달했습니다" % 최대주제())
        이미 = {r["본문"] for r in 현재}
        현재묶음 = next((m for m in 현재묶음들 if set(별칭) & m["별칭"]), None)
        남은칸 = 주제당최대() - len(현재묶음["기록"] if 현재묶음 else [])
        if 남은칸 <= 0:
            return []
        when = time.strftime("%Y-%m-%dT%H:%M:%S")
        후보 = []
        for 찾음 in 찾은:
            출처, 글 = 찾음["출처"], 찾음["본문"]
            if 글 in 이미 or len(후보) >= 남은칸:
                continue
            기록 = {"주제": 저장주제, "주제별칭": 저장별칭, "질의": 질의,
                    "수집형식": 3,
                    "출처": 출처, "URL": 찾음.get("URL", ""),
                    "제목": 찾음.get("제목", ""), "본문": 글,
                    "문장들": 찾음["문장들"], "대목들": 찾음["대목들"],
                    "질문표현": [t.format(주제=저장주제) for t in _질문틀] + [질의],
                    "수집시각": when}
            줄 = json.dumps(기록, ensure_ascii=False) + "\n"
            후보.append((기록, 줄))

        # 검사 시점에는 상한 아래여도 이번 배치 전체를 붙이면 넘을 수 있다.
        # UTF-8 실제 바이트로 재고, 새 주제는 최소 출처 수가 다 들어갈 때만 쓴다.
        현재크기 = os.path.getsize(경로) if os.path.exists(경로) else 0
        새것, 줄들, 더할크기 = [], [], 0
        for 기록, 줄 in 후보:
            바이트 = len(줄.encode("utf-8"))
            if 현재크기 + 더할크기 + 바이트 > 수집최대바이트():
                break
            새것.append(기록)
            줄들.append(줄)
            더할크기 += 바이트
        if not 현재묶음 and len({r["출처"] for r in 새것}) < 최소출처:
            if 후보 and not 새것:
                raise 학습실패("수집 파일 크기 상한 안에 새 기록을 넣을 공간이 없습니다")
            return []
        if 줄들:
            try:
                with open(경로, "a", encoding="utf-8") as f:
                    f.writelines(줄들)
            except OSError as e:
                raise 학습실패("수집 파일을 기록할 수 없습니다: %s" % e) from e
    return 새것


def 수집읽기(경로):
    out = []
    if 경로 and os.path.exists(경로):
        with open(경로, encoding="utf-8") as f:
            for 줄 in f:
                줄 = 줄.strip()
                if not 줄:
                    continue
                try:
                    d = json.loads(줄)
                    if d.get("주제") and d.get("본문"):
                        out.append(d)
                except ValueError:
                    pass
    return out


def 얹기(g, 기록들):
    """수집 기록을 그래프에 붙인다. 노드 이름은 전부 접두사로 표시해 둔다 —
    어느 것이 기계가 주워온 것인지 그래프만 보고도 알 수 있어야 한다."""
    g["_주제별칭"] = {}
    g["_주제사실"] = {}
    g["_주제대목"] = {}
    # 발췌만 있던 구버전 기록은 감사 로그로 남기되 지식 그래프에는 얹지 않는다.
    # 원문에서 가져온 완결 문장 목록이 있는 기록만 사실 노드가 된다.
    채택 = [r for r in 기록들 if r.get("수집형식") == 3 and r.get("문장들") and r.get("대목들")
          and any(주제관련(r.get("주제"), s) for s in r["문장들"])]
    for 묶음 in _주제묶음(채택):
        주제, rs = 묶음["이름"], 묶음["기록"]
        주장 = "지식_" + 주제
        문장전부 = [s for r in rs for s in r.get("문장들", [])]
        문장전부 = list(dict.fromkeys(문장전부))
        g["_주제별칭"][주장] = sorted(_유효별칭(주제, 문장전부), key=len, reverse=True)
        # 주제 루트와 각 사실을 나눠야 그래프가 실제로 무엇을 배웠는지 보인다.
        g["공통층"][주장] = list(dict.fromkeys([주제] + [q for r in rs for q in r.get("질문표현", [])]))
        g["_주제사실"][주장] = []
        g["_주제대목"][주장] = []

        도메인 = sorted({r["출처"] for r in rs})
        g.setdefault("출처", {})[주장] = "웹 %d곳 · %s%s" % (
            len(도메인), ", ".join(도메인[:2]), " 외" if len(도메인) > 2 else "")

        사실번호, 출처묶음 = {}, {}
        for r in rs:
            출처묶음.setdefault(r["출처"], []).append(r)
        for i, (출처, 출처기록들) in enumerate(sorted(출처묶음.items()), 1):
            대표 = 출처기록들[-1]
            출처노드 = "출처_%s_%d" % (주제, i)
            g["사례층"][출처노드] = [대표.get("제목") or 출처]
            g["출처"][출처노드] = 대표.get("URL") or 출처
            if 출처노드 not in g.setdefault("증거", []):
                g["증거"].append(출처노드)
            for r in 출처기록들:
                for 대목 in r.get("대목들", []):
                    if 대목:
                        g["_주제대목"][주장].append({"출처": 출처,
                                                    "문장들": list(대목)})
                for 문장 in r.get("문장들", []):
                    if 문장 not in 사실번호:
                        사실번호[문장] = len(사실번호) + 1
                        사실 = "지식_%s_사실_%d" % (주제, 사실번호[문장])
                        g["공통층"][사실] = [문장]
                        g["출처"][사실] = r.get("URL") or r["출처"]
                        g["_주제사실"][주장].append(사실)
                        g["엣지"].append([사실, "충족", 주장])
                    else:
                        사실 = "지식_%s_사실_%d" % (주제, 사실번호[문장])
                    edge = [출처노드, "증명", 사실]
                    if edge not in g["엣지"]:
                        g["엣지"].append(edge)

        g["엣지"].append([주장, "충족", g["목표"]])
    return g


def 불러오기(kg경로):
    """engine.load() 를 그대로 쓰되 파싱 직후에 수집분을 얹는다.

    load() 뒤쪽(학습 덧칠·검증·관련개념·벡터)을 여기로 복사하면 engine 이
    바뀔 때 조용히 어긋난다. 파싱 함수만 잠깐 감싸서 나머지를 전부 물려받는다."""
    원래 = eng.kg읽기
    기록 = 수집읽기(수집경로(kg경로))

    def 덧칠(경로):
        return 얹기(원래(경로), 기록)

    eng.kg읽기 = 덧칠
    try:
        return eng.load(kg경로)
    finally:
        eng.kg읽기 = 원래


def 묻다(g, 말):
    """→ (아는 주제인가, 답).

    주제는 원문에서 확인된 별칭으로 정확히 고르고, 답은 그 주제 아래의 완결
    사실 노드 가운데 질문과 가까운 것 최대 여섯 개를 고른다. 잘린 발췌의 끝을
    지어내지 않고 원문 문장을 문단으로 조립한다.

    모르는 주제에 대고 억지로 대답하지 않는다. '무관하다'가 아니라
    '아직 모른다'로 답한다."""
    주제표 = []
    for n, 별칭 in (g.get("_주제별칭") or {}).items():
        주제표.extend((a, n) for a in 별칭)
    걸림 = next(((a, n) for a, n in sorted(주제표, key=lambda x: len(x[0]), reverse=True)
                if a and a in 말), None)
    if not 걸림:
        모름 = ((g.get("공통층") or {}).get("상태_지식부족")
                or (g.get("무관층") or {}).get("_타죄명:상태_지식부족")
                or ["아직 그 내용을 모릅니다"])
        return False, 모름[0]

    걸린주제, 주장 = 걸림
    사실들 = (g.get("_주제사실") or {}).get(주장, [])
    if not 사실들:
        return False, "아직 원문에서 완결된 지식을 만들지 못했습니다."
    대목들 = (g.get("_주제대목") or {}).get(주장, [])
    기준 = _vec(말)
    후보 = []
    for order, item in enumerate(대목들):
        text = " ".join(item.get("문장들") or [])
        if not text or "..." in text or "…" in text:
            continue
        score = float((_vec(text) @ 기준).max())
        후보.append((score, order, item.get("출처"), text))
    if 후보:
        후보.sort(reverse=True)
        최고 = 후보[0][0]
        열거요청 = any(x in 말 for x in ("목록", "장점", "단점", "단계", "순서", "종류", "이유"))
        열거시작 = re.compile(r"^(첫째|둘째|셋째|넷째|다섯째|먼저|다음으로|마지막으로|\d+[.)])")
        답, 본문, 출처별 = [], set(), {}
        # 고정 '6문장'이 아니라 최고 대목과 의미상 가까운 완결 문단을 고른다.
        # 12k 안전망에서도 문단 중간은 자르지 않는다.
        for score, order, source, text in 후보:
            if score < max(0.18, 최고 - 0.10) or text in 본문:
                continue
            if not 열거요청 and 열거시작.match(text):
                continue
            if sum(len(x) for x in 답) + len(text) > 12000:
                continue
            # 한 출처의 반복 서술이 답을 독점하지 않게 하되 원문 다양성은 유지한다.
            if 출처별.get(source, 0) >= 3:
                continue
            본문.add(text)
            출처별[source] = 출처별.get(source, 0) + 1
            답.append((order, text))
        if 답:
            # 같은 점수권 안에서는 원문 순서가 담화 연결을 보존한다.
            return True, "\n\n".join(text for _order, text in sorted(답))

    # 구버전/예외 그래프의 대목 정보가 없을 때도 완결 사실만 반환한다.
    행 = [g["공통층"][n][0] for n in 사실들 if g["공통층"].get(n)]
    return True, "\n\n".join(x for x in 행 if "..." not in x and "…" not in x)


# ── CLI ─────────────────────────────────────────────────────────────────
def _쓰임():
    print(__doc__.strip())
    print("""
사용법
  python web_learn.py --배우다 <주제> [--질의 "검색어"] [--개수 10] [--새로고침]
  python web_learn.py --묻다   <말>
  python web_learn.py --보기
  python web_learn.py --check

  --그래프 <경로>   기본 graphs/graph_자가학습.kg""")


def _주():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        return _쓰임()

    def 값(이름, 기본=None):
        return argv[argv.index(이름) + 1] if 이름 in argv and argv.index(이름) + 1 < len(argv) else 기본

    kg = 값("--그래프", "graphs/graph_자가학습.kg")

    if "--check" in argv:
        return _자체검사(kg)

    if "--보기" in argv:
        기록 = 수집읽기(수집경로(kg))
        채택 = [r for r in 기록 if 주제관련(r.get("주제"), r.get("본문"))]
        제외 = [r for r in 기록 if r not in 채택]
        묶음들 = _주제묶음(채택)
        print("수집 파일: %s  (기록 %d개, 채택 %d개, 제외 %d개, 주제 %d개)"
              % (수집경로(kg), len(기록), len(채택), len(제외), len(묶음들)))
        for 묶음 in 묶음들:
            주제, rs = 묶음["이름"], 묶음["기록"]
            print("\n[%s] 출처 %d곳" % (주제, len({r["출처"] for r in rs})))
            for r in rs:
                print("   · %-24s %s" % (r["출처"][:24], r["본문"][:56]))
        if 제외:
            print("\n[품질 필터로 제외 — 원본 감사 로그에는 보존]")
            for r in 제외:
                print("   · %-12s %-24s %s"
                      % (r["주제"][:12], r.get("출처", "")[:24], r["본문"][:56]))
        return

    if "--배우다" in argv:
        주제 = 값("--배우다")
        질의 = 값("--질의", 주제)
        try:
            새것 = 배우기(kg, 주제, 질의, int(값("--개수", "10")),
                         강제="--새로고침" in argv)
        except 학습실패 as e:
            print("[학습 실패] %s" % e)
            return 1
        print("'%s' 검색 → 새로 %d건 수집 (옆파일: %s)" % (질의, len(새것), 수집경로(kg)))
        for r in 새것:
            print("   · %-24s %s" % (r["출처"][:24], r["본문"][:56]))
        if not 새것:
            print("   (이미 갖고 있는 내용이거나 검색 결과가 없다)")
        return

    if "--묻다" in argv:
        g = 불러오기(kg)
        말 = 값("--묻다")
        아는가, 답 = 묻다(g, 말)
        학습시도 = False
        if not 아는가:
            추출주제, _별칭 = 주제추출(g, 말)
            if 추출주제:
                학습시도 = True
                실패문구 = None
                print("[자동학습] 그래프 표지를 이용해 '%s' 주제를 추출했습니다. 스스로 배웁니다..."
                      % 추출주제)
                try:
                    새것 = 배우기(kg, 추출주제, 말, int(값("--개수", "10")), 최소출처=2)
                except 학습실패 as e:
                    실패문구 = str(e)
                    새것 = []
                if 새것:
                    g = 불러오기(kg)
                    아는가, 답 = 묻다(g, 말)
                elif not 아는가:
                    답 = (("자동 학습을 완료하지 못했습니다: " + 실패문구) if 실패문구 else
                           "서로 다른 출처 두 곳에서 주제를 확인하지 못해 지식으로 채택하지 않았습니다.")

        print(답)
        if not 아는가:
            print("   (배우려면: python web_learn.py --배우다 <주제>)")
        return 1 if 학습시도 and not 아는가 else 0

    _쓰임()


def _자체검사(kg):
    문제 = []
    t = "재료 준비 | 조리 # 완성\n두 번째 줄"
    s = 살균(t, kg안전=True)
    if "\n" in s or "|" in s or "#" in s:
        문제.append("살균이 개행/구분자를 남긴다: %r" % s)
    if 살균("<b>가</b>격은 3000원 # 별도")[:2] != "가격":
        문제.append("태그 제거 실패")
    문장시험 = 완결문장들("양자역학은 설명 도중 잘린 내용입니다... "
                         "양자역학은 미시 세계를 설명하는 물리 이론입니다.", "양자역학")
    if 문장시험 != ["양자역학은 미시 세계를 설명하는 물리 이론입니다."]:
        문제.append("잘린 발췌를 버리고 완결 문장만 고르지 못한다: %r" % 문장시험)
    g = 불러오기(kg)
    if not g.get("공통층"):
        문제.append("그래프가 비었다")
    for n in (g.get("출처") or {}):
        if n not in g["공통층"] and n not in g["사례층"] and n not in g.get("무관층", {}):
            문제.append("출처가 붙은 '%s' 이 어느 층에도 없다" % n)
    주제, 별칭 = 주제추출(g, "양자역학이 뭐야")
    if 주제 != "양자역학이" or "양자역학" not in 별칭:
        문제.append("조사 별칭 추출 실패: %r %r" % (주제, 별칭))
    if 주제추출(g, "초전도체란")[0] != "초전도체":
        문제.append("'~란' 질문에서 주제를 못 뽑는다")
    if 주제추출(g, "폴란드가 뭐야")[0] != "폴란드가":
        문제.append("주제 내부의 질문 표지 글자를 지운다")
    if 주제추출(g, "뭐야")[0] is not None:
        문제.append("표지만 있는 질문에서 빈 주제를 학습한다")
    if not 주제관련("양자역학이", "양자역학은 물리학의 이론 체계다"):
        문제.append("조사 변형이 있는 관련 스니펫을 버린다")
    if 주제관련("양자역학이", "양자컴퓨터는 0과 1을 동시에 사용한다"):
        문제.append("주제를 직접 말하지 않은 스니펫을 채택한다")
    if "호랑" in _유효별칭("호랑이", ["호랑이는 고양잇과 동물이다"]):
        문제.append("명사 끝 글자를 조사로 오인해 거짓 별칭을 만든다")
    if "양자역학" not in _유효별칭("양자역학이", ["양자역학은 물리 이론이다"]):
        문제.append("본문으로 확인된 조사 제거 별칭을 버린다")

    # 서로 다른 표면형도 별칭이 겹치면 한 주제다.
    시험기록 = [
        {"주제": "양자역학이", "본문": "양자역학은 미시 세계의 이론이다.",
         "수집형식": 3, "문장들": ["양자역학은 미시 세계의 이론이다."],
         "대목들": [["양자역학은 미시 세계의 이론이다."]], "출처": "a",
         "주제별칭": ["양자역학이", "양자역학"]},
        {"주제": "양자역학", "본문": "양자역학의 측정에는 고유한 규칙이 있다.",
         "수집형식": 3, "문장들": ["양자역학의 측정에는 고유한 규칙이 있다."],
         "대목들": [["양자역학의 측정에는 고유한 규칙이 있다."]], "출처": "b",
         "주제별칭": ["양자역학"]},
    ]
    if len(_주제묶음(시험기록)) != 1:
        문제.append("조사만 다른 주제가 중복 묶음으로 남는다")
    시험그래프 = {"공통층": {}, "사례층": {}, "무관층": {}, "엣지": [],
                  "출처": {}, "목표": "목표"}
    같은출처기록 = 시험기록 + [
        {"주제": "양자역학", "본문": "양자역학은 파동 함수를 사용한다.",
         "수집형식": 3, "문장들": ["양자역학은 파동 함수를 사용한다."],
         "대목들": [["양자역학은 파동 함수를 사용한다."]], "출처": "a",
         "주제별칭": ["양자역학"]},
        {"주제": "양자역학", "본문": "양자컴퓨터는 중첩을 계산에 쓴다.",
         "수집형식": 3, "문장들": ["양자컴퓨터는 중첩을 계산에 쓴다."],
         "대목들": [["양자컴퓨터는 중첩을 계산에 쓴다."]], "출처": "c",
         "주제별칭": ["양자역학"]},
    ]
    얹기(시험그래프, 같은출처기록)
    증명수 = len([e for e in 시험그래프["엣지"] if e[1] == "증명"])
    출처노드수 = len([n for n in 시험그래프["사례층"] if n.startswith("출처_")])
    if 출처노드수 != 2 or 증명수 != 3:
        문제.append("출처와 완결 사실 노드 구성이 틀렸다: 출처 %d, 증명 %d"
                   % (출처노드수, 증명수))
    if any("양자컴퓨터" in s for v in 시험그래프["사례층"].values() for s in v):
        문제.append("과거 로그의 무관 스니펫을 런타임 지식으로 얹는다")

    # 네트워크 대신 고정 검색 결과를 넣어 저장·품질 필터·재수집 방지를 함께 잰다.
    import tempfile
    원검색 = globals()["검색"]
    try:
        with tempfile.TemporaryDirectory(prefix="web-learn-check-") as td:
            시험kg = os.path.join(td, "시험.kg")
            globals()["검색"] = lambda _q, 개수=10: [
                ("a.example", "양자역학은 미시 세계를 설명하는 물리학의 이론 체계입니다."),
                ("b.example", "양자역학의 상태와 측정은 고전 역학과 다른 규칙을 따릅니다."),
                ("c.example", "양자컴퓨터는 0과 1을 동시에 사용해 계산할 수 있습니다."),
            ]
            새것 = 배우기(시험kg, "양자역학이", "양자역학이 뭐야", 3, 최소출처=2)
            if len(새것) != 2 or any(r["출처"] == "c.example" for r in 새것):
                문제.append("검색 품질 필터가 무관 스니펫을 거르지 못한다: %r" % 새것)
            if any(r["주제"] != "양자역학" or r.get("수집형식") != 3 for r in 새것):
                문제.append("검증된 조사 제거형을 대표 주제로 저장하지 못한다: %r" % 새것)
            if 배우기(시험kg, "양자역학", "양자역학 설명해줘", 3, 최소출처=2):
                문제.append("같은 주제를 조사만 바꿔 즉시 중복 수집한다")

            # 운영 상한과 잠금도 실제 파일 경계에서 잰다.
            환경이름 = ("KG_LEARN_MAX_TOPICS", "KG_LEARN_MAX_RECORDS",
                    "KG_LEARN_MAX_BYTES", "KG_LEARN_COOLDOWN")
            원환경 = {k: os.environ.get(k) for k in 환경이름}
            try:
                globals()["검색"] = lambda q, 개수=10: [
                    ("a.example", "%s에 관한 첫 번째 독립 출처의 충분히 긴 설명입니다." % q),
                    ("b.example", "%s에 관한 두 번째 독립 출처의 충분히 긴 설명입니다." % q),
                    ("c.example", "%s에 관한 세 번째 독립 출처의 충분히 긴 설명입니다." % q),
                ]
                os.environ["KG_LEARN_MAX_RECORDS"] = "2"
                제한kg = os.path.join(td, "제한.kg")
                제한기록 = 배우기(제한kg, "별하나", "별하나", 3, 최소출처=2)
                if len(제한기록) != 2 or len(수집읽기(수집경로(제한kg))) != 2:
                    문제.append("주제당 기록 상한을 넘거나 덜 기록한다")

                os.environ["KG_LEARN_MAX_TOPICS"] = "1"
                try:
                    배우기(제한kg, "별둘", "별둘", 2, 최소출처=2)
                    문제.append("전체 주제 상한을 넘겨 새 주제를 기록한다")
                except 학습실패:
                    pass

                잠금kg = os.path.join(td, "잠금.kg")
                잠금파일 = 수집경로(잠금kg) + ".lock"
                with open(잠금파일, "w", encoding="ascii") as f:
                    f.write("testing\n")
                try:
                    배우기(잠금kg, "잠금시험", "잠금시험", 2, 최소출처=2)
                    문제.append("동시 수집 잠금을 무시하고 기록한다")
                except 학습실패:
                    pass
                finally:
                    try:
                        os.unlink(잠금파일)
                    except FileNotFoundError:
                        pass

                os.environ["KG_LEARN_MAX_BYTES"] = "100"
                작은kg = os.path.join(td, "작은.kg")
                try:
                    배우기(작은kg, "크기시험", "크기시험", 2, 최소출처=2)
                    문제.append("배치 쓰기로 파일 크기 상한을 넘긴다")
                except 학습실패:
                    pass
                if os.path.exists(수집경로(작은kg)):
                    문제.append("크기 상한에 걸린 불완전 배치를 일부 기록한다")

                os.environ["KG_LEARN_MAX_RECORDS"] = "1"
                try:
                    배우기(os.path.join(td, "설정오류.kg"), "설정오류", "설정오류",
                         2, 최소출처=2)
                    문제.append("필수 출처보다 작은 기록 상한을 허용한다")
                except 학습실패:
                    pass
            finally:
                for k, v in 원환경.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            def 끊김(_q, 개수=10):
                raise urllib.error.URLError("offline")
            globals()["검색"] = 끊김
            try:
                배우기(os.path.join(td, "오프라인.kg"), "초전도체", "초전도체란", 3)
                문제.append("네트워크 실패를 성공으로 처리한다")
            except 학습실패:
                pass
    finally:
        globals()["검색"] = 원검색
    print("자체검사: %s" % ("통과" if not 문제 else "%d건 실패" % len(문제)))
    for x in 문제:
        print("   - " + x)
    return 1 if 문제 else 0


if __name__ == "__main__":
    sys.exit(_주() or 0)
