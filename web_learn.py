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
4. 문장은 만들지 않는다. 주워온 문장을 그대로 노드의 예시로 두고,
   대답할 때 engine.문장() 이 사용자 말투에 가장 가까운 예시를 고른다.
   고르는 것이지 생성이 아니다 — 그래서 환각도 주입 표면도 늘지 않는다.

수집량·동시 쓰기·재수집 간격에는 운영 상한이 있다. KG_LEARN_MAX_TOPICS,
KG_LEARN_MAX_RECORDS, KG_LEARN_MAX_BYTES, KG_LEARN_COOLDOWN 환경변수로
배포 규모에 맞게 조정할 수 있다.

인코더는 KG_ENCODER=문자 를 기본으로 둔다. 토큰을 쓰지 않는다.
"""
import html
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


def 검색(질의, 개수=10, 최소길이=40):
    """열린 웹 검색. (출처, 본문) 목록을 돌려준다.

    스니펫을 하나만 쓰면 그 블로그 한 곳이 곧 진실이 된다. 여러 개를 받아야
    교차검증이 가능해지므로 기본값을 10 으로 둔다."""
    req = urllib.request.Request(
        "https://lite.duckduckgo.com/lite/",
        data=urllib.parse.urlencode({"q": 질의}).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        본문 = r.read().decode("utf-8", "replace")

    링크 = [urllib.parse.urlparse(u).netloc for u in _링크.findall(본문)]
    조각 = [살균(s) for s in _스니펫.findall(본문)]
    out, 본것 = [], set()
    for i, 글 in enumerate(조각):
        if len(글) < 최소길이 or 글 in 본것:
            continue                       # 너무 짧은 것은 근거가 못 된다
        본것.add(글)
        out.append((링크[i] if i < len(링크) else "출처미상", 글))
        if len(out) >= 개수:
            break
    return out


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
    if 같은묶음 and not 강제 and _최근인가(같은묶음["기록"], 재수집대기초()):
        return []
    if not 같은묶음 and len(기존묶음) >= 최대주제():
        raise 학습실패("자동 학습 주제 상한(%d개)에 도달했습니다" % 최대주제())
    if os.path.exists(경로) and os.path.getsize(경로) >= 수집최대바이트():
        raise 학습실패("수집 파일 크기 상한(%d바이트)에 도달했습니다" % 수집최대바이트())

    try:
        찾은 = 검색(질의, 개수=max(개수 * 2, 개수))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise 학습실패("웹 검색에 연결하지 못했습니다: %s" % getattr(e, "reason", e)) from e

    # 같은 도메인의 여러 스니펫은 교차검증 여러 곳으로 세지 않는다.
    고른것, 도메인 = [], set()
    for 출처, 글 in 찾은:
        if 출처 == "출처미상" or 출처 in 도메인 or not 주제관련(주제, 글):
            continue
        도메인.add(출처)
        고른것.append((출처, 글))
        if len(고른것) >= 개수:
            break
    찾은 = 고른것
    if len({출처 for 출처, _ in 찾은}) < 최소출처:
        return []
    if not 찾은:
        return []
    저장별칭 = _유효별칭(주제, [글 for _, 글 in 찾은])
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
        for 출처, 글 in 찾은:
            if 글 in 이미 or len(후보) >= 남은칸:
                continue
            기록 = {"주제": 주제, "주제별칭": 저장별칭, "질의": 질의,
                    "출처": 출처, "본문": 글,
                    "질문표현": [t.format(주제=주제) for t in _질문틀] + [질의],
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
    # 예전 버전에서 이미 들어간 무관 스니펫도 원본 로그를 지우지 않고 런타임에서
    # 제외한다. 감사 기록은 남고, 답과 증거 수에는 영향을 주지 않는다.
    채택 = [r for r in 기록들 if 주제관련(r.get("주제"), r.get("본문"))]
    for 묶음 in _주제묶음(채택):
        주제, rs = 묶음["이름"], 묶음["기록"]
        주장 = "지식_" + 주제
        본문들 = []
        for r in rs:
            if r["본문"] not in 본문들:
                본문들.append(r["본문"])
        g["_주제별칭"][주장] = sorted(_유효별칭(주제, 본문들), key=len, reverse=True)
        # 예시가 여럿인 것이 곧 말투 재료다. engine.문장() 이 사용자 발화에
        # 가장 가까운 것을 고른다.
        g["공통층"][주장] = 본문들

        도메인 = sorted({r["출처"] for r in rs})
        g.setdefault("출처", {})[주장] = "웹 %d곳 · %s%s" % (
            len(도메인), ", ".join(도메인[:2]), " 외" if len(도메인) > 2 else "")


        # 출처 도메인 하나가 증거 하나. 새로고침 때 같은 사이트의 다른 발췌가
        # 더 들어와도 독립 증거 수를 부풀리지 않는다.
        출처별 = {}
        for r in rs:
            출처별.setdefault(r["출처"], []).append(r["본문"])
        for i, (출처, 발췌들) in enumerate(sorted(출처별.items()), 1):
            n = "출처_%s_%d" % (주제, i)
            g["사례층"][n] = list(dict.fromkeys(발췌들))
            g["출처"][n] = 출처
            g["엣지"].append([n, "증명", 주장])

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

    답을 두 벡터로 나눠 만든다. 하나로는 안 된다:

      · 어느 주제인가 — 주제 낱말이 살아 있어야 갈린다. 지우면 남는 것이
        "재료 알려줘" 뿐이라 주제끼리 구분이 사라진다(실제로 김치찌개 질문에
        까르보나라 발췌가 나왔다). 발화 그대로 잰다 —
        측정 6/6, 1위 0.27~0.50 vs 2위 0.17~0.28.
      · 어느 발췌인가(말투) — 주제 낱말이 빠져야 갈린다. 남기면 주제를
        아홉 번 되풀이하는 발췌가 어떤 질문에도 이겨 말투 선택이 죽는다.
        주제를 뺀 나머지로 잰다.

    judge() 는 기준 벡터를 하나만 쓰므로 둘을 동시에 만족시킬 수 없다.
    그래서 판정 대신 그래프의 대사와 engine.문장() 으로 직접 조립한다.
    문장은 여전히 만들지 않는다 — 고르기만 한다.

    모르는 주제에 대고 억지로 대답하지 않는다. '무관하다'가 아니라
    '아직 모른다'로 답한다."""
    주제표 = []
    for n in g.get("공통층", {}):
        if n.startswith("지식_"):
            별칭 = (g.get("_주제별칭") or {}).get(n) or 주제별칭(n[len("지식_"):])
            주제표.extend((a, n) for a in 별칭)
    걸림 = next(((a, n) for a, n in sorted(주제표, key=lambda x: len(x[0]), reverse=True)
                if a and a in 말), None)
    if not 걸림:
        모름 = ((g.get("공통층") or {}).get("상태_지식부족")
                or (g.get("무관층") or {}).get("_타죄명:상태_지식부족")
                or ["아직 그 내용을 모릅니다"])
        return False, 모름[0]

    걸린주제, 주장 = 걸림
    나머지 = 말.replace(걸린주제, " ").strip() or 말
    발췌 = eng.문장(g, 주장, _vec(나머지))

    말틀 = g["대사"].get("인정_말", "{말}")
    줄 = [말틀.format(말=발췌, ev="", claim=주장, bad="", 반격말="")]
    출처 = (g.get("출처") or {}).get(주장)
    if 출처 and g["대사"].get("출처"):
        줄.append(g["대사"]["출처"].format(출처=출처, claim=주장))
    return True, " ".join(줄)


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
        {"주제": "양자역학이", "본문": "양자역학은 미시 세계의 이론이다", "출처": "a",
         "주제별칭": ["양자역학이", "양자역학"]},
        {"주제": "양자역학", "본문": "양자역학의 측정에는 고유한 규칙이 있다", "출처": "b",
         "주제별칭": ["양자역학"]},
    ]
    if len(_주제묶음(시험기록)) != 1:
        문제.append("조사만 다른 주제가 중복 묶음으로 남는다")
    시험그래프 = {"공통층": {}, "사례층": {}, "무관층": {}, "엣지": [],
                  "출처": {}, "목표": "목표"}
    같은출처기록 = 시험기록 + [
        {"주제": "양자역학", "본문": "양자역학은 파동 함수를 사용한다", "출처": "a",
         "주제별칭": ["양자역학"]},
        {"주제": "양자역학", "본문": "양자컴퓨터는 중첩을 계산에 쓴다", "출처": "c",
         "주제별칭": ["양자역학"]},
    ]
    얹기(시험그래프, 같은출처기록)
    증명수 = len([e for e in 시험그래프["엣지"] if e[1] == "증명"])
    if 증명수 != 2:
        문제.append("같은 출처의 여러 발췌가 독립 증거로 부풀려진다: %d" % 증명수)
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
