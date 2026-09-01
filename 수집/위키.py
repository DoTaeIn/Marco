# -*- coding: utf-8 -*-
"""위키백과에서 글을 받아 자료/ 에 넣는다. 검색은 답하는 도구가 아니라 자료를 늘리는 도구다.

    python 위키.py 정당방위 명예훼손        # 받아서 자료/웹/ 에 저장
    python 위키.py --찾기 저작권             # 무엇이 있는지 먼저 본다
    python 위키.py --그림 정당방위 편의점    # 그림 + 캡션 -> 자료/그림/
    python 위키.py --그림 --아무거나 200     # 아무 문서 200개에서. 범용 표본

받은 글은 그래프에 바로 들어가지 않는다. 자료/ 에 놓이고, 거기서부터는
기존 흐름 그대로다 — 짓기.py 로 그래프를 만들거나 engine.py --mine 으로
노드 후보를 뽑고 사람이 확인한다.

이 순서를 지키는 이유는 하나다. 검색 결과는 근거가 아니라 남의 주장이다.
그것을 곧바로 답으로 내보내면 이 엔진이 파는 유일한 것(모든 답에 영수증)이
무너진다. 자료로 들어와 사람이 확인하고 그래프가 되어야 근거가 된다.

키가 필요 없다. 법제처 API 와 달리 위키백과는 열려 있다.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

밖 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "자료", "웹")
헤더 = {"User-Agent": "Objection/0.1 (https://github.com/DoTaeIn/Objection) python-urllib"}
API = "https://ko.wikipedia.org/w/api.php?"


_사이 = float(os.environ.get("위키_간격", "1.0"))   # API 호출 최소 간격(초)
_마지막 = [0.0]


def _쉬어가기():
    """남의 서버다. 간격은 부르는 쪽마다 지키는 게 아니라 여기서 한 번 지킨다."""
    남은 = _사이 - (time.time() - _마지막[0])
    if 남은 > 0:
        time.sleep(남은)
    _마지막[0] = time.time()


def _부르기(**인자):
    """API 한 번. 429/503 이면 물러났다가 다시 묻는다.

    남의 서버다. 그림을 받으려면 문서 하나에 여러 번 불러야 해서 글만 받을
    때보다 훨씬 빨리 벽에 닿는다 — 무작위 20개에서 8개 만에 429 가 났다.
    maxlag 는 위키미디어가 정한 예의다. 복제 지연이 크면 우리가 기다린다."""
    인자.setdefault("format", "json")
    인자.setdefault("maxlag", 5)
    url = API + urllib.parse.urlencode(인자, encoding="utf-8")
    req = urllib.request.Request(url, headers=헤더)
    쉼 = 2.0
    for _ in range(8):
        _쉬어가기()
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503):
                raise
            기다림 = e.headers.get("Retry-After")
            잠 = float(기다림) if 기다림 and 기다림.isdigit() else 쉼
            print("   (%d. %.0f초 쉼)" % (e.code, 잠), file=sys.stderr)
            time.sleep(잠)
            쉼 = min(쉼 * 2, 30)
            continue
        # maxlag 초과는 200 으로 오고 error 안에 들어 있다
        if r.get("error", {}).get("code") == "maxlag":
            print("   (maxlag. %.0f초 쉼)" % 쉼, file=sys.stderr)
            time.sleep(쉼)
            쉼 = min(쉼 * 2, 30)
            continue
        return r
    raise RuntimeError("위키가 계속 물러나라고 한다. 나중에 다시.")


def 그림있나(제목들):
    """제목 50개씩 묶어 '그림이 있는 문서' 만 걸러낸다.

    무작위 문서는 대부분 토막글이라 그림이 없다. 그런데 캡션을 얻으려면
    문서마다 위키텍스트를 따로 불러야 한다 — 없는 문서까지 부르면 호출이
    몇 배가 되고 그래서 429 를 맞았다. 이 한 번으로 50개를 걸러낸다."""
    있는것 = {}
    for k in range(0, len(제목들), 50):
        묶음 = 제목들[k:k + 50]
        r = _부르기(action="query", prop="images", imlimit="max",
                    titles="|".join(묶음), redirects=1)
        for 쪽 in r.get("query", {}).get("pages", {}).values():
            쓸것 = [_접두어없이(x["title"]) for x in 쪽.get("images", [])]
            쓸것 = [x for x in 쓸것
                    if _그림확장.search(x) and not _잡그림.search(x)]
            if 쓸것:
                있는것[쪽["title"]] = 쓸것
    return 있는것


def 찾기(말, 수=8):
    """-> [{제목, 단어수}]"""
    r = _부르기(action="query", list="search", srsearch=말, srlimit=수)
    return [{"제목": x["title"], "단어수": x.get("wordcount", 0)}
            for x in r.get("query", {}).get("search", [])]


def 받기(제목):
    """문서 하나의 본문. 위키 문법을 걷어낸 평문."""
    r = _부르기(action="query", prop="extracts", titles=제목,
                explaintext=1, exsectionformat="plain", redirects=1)
    쪽 = list(r.get("query", {}).get("pages", {}).values())
    if not 쪽 or "extract" not in 쪽[0]:
        return None
    본문 = 쪽[0]["extract"]
    본문 = re.sub(r"\n{3,}", "\n\n", 본문).strip()
    return 본문 or None


def 저장(제목, 본문):
    os.makedirs(밖, exist_ok=True)
    안전 = re.sub(r'[\\/:*?"<>|]', "", 제목).replace(" ", "_")
    경로 = os.path.join(밖, "위키_%s.txt" % 안전)
    with open(경로, "w", encoding="utf-8") as f:
        f.write("# 출처: 위키백과 「%s」 (https://ko.wikipedia.org/wiki/%s)\n"
                % (제목, urllib.parse.quote(제목.replace(" ", "_"))))
        f.write("# 받은 날: %s\n\n" % time.strftime("%Y-%m-%d"))
        f.write(본문 + "\n")
    return 경로


# ───────────────────────────── 그림 ─────────────────────────────
# 그림만 받아서는 아무것도 못 짓는다. 시각 단어를 낱말에 잇는 것은 학습이
# 아니라 공기(共起)인데, 그 짝을 공짜로 만들어 주는 것이 캡션이다.
# 그래서 그림과 캡션은 반드시 한 줄로 묶어서 받는다 —
# 사람이 라벨을 달지 않는다는 뜻이기도 하다. 캡션이 이미 라벨이다.

그림밖 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "자료", "그림")
목록 = "그림목록.jsonl"

# 문서마다 딸려오는 장식들. 내용과 아무 상관이 없는데 모든 문서에 똑같이
# 들어가서, 그대로 두면 그 무늬가 모든 낱말과 공기하는 것으로 세어진다.
_잡그림 = re.compile(
    r"(?i)(commons|wiki[a-z]*-logo|logo|icon|아이콘|ambox|question[_ ]book|"
    r"symbol|stub|스텁|edit-|padlock|crystal|nuvola|folder|button|blank|"
    r"spacer|arrow|flag[_ ]of|국기)")
_그림확장 = re.compile(r"(?i)\.(jpe?g|png|gif|webp)$")
_꾸밈말 = re.compile(
    r"(?i)^(thumb|thumbnail|섬네일|썸네일|frame|frameless|border|right|left|"
    r"center|centre|none|가운데|오른쪽|왼쪽|upright(=[\d.]+)?|"
    r"\d+\s*x?\s*\d*\s*px|alt=.*|link=.*|lang=.*|page=.*|class=.*|"
    r"baseline|middle|sub|super|top|bottom|text-top|text-bottom)$")


def _칸들(글, 시작, 대괄호):
    """파일 이름 뒤에 붙은 칸(|thumb|300px|캡션)을 잘라 온다.

    그림이 쓰이는 자리가 세 가지인데 끝나는 표가 다르다.
      [[파일:x.jpg|thumb|캡션]]     -> 짝 맞는 ]] 에서. 캡션 안에 또 [[ ]] 가 있다
      <gallery> 파일:x.jpg|캡션     -> 줄 끝에서
      {{갤러리2 |파일:x.jpg|캡션 }} -> 줄 끝이나 }} 에서
    처음엔 대괄호만 봤더니 CU 문서에서 0장이 나왔다. 그림은 갤러리에 있다."""
    if 대괄호:
        깊이, k = 1, 시작
        while k < len(글):
            if 글.startswith("[[", k):
                깊이 += 1
                k += 2
            elif 글.startswith("]]", k):
                깊이 -= 1
                if 깊이 == 0:
                    return 글[시작:k]
                k += 2
            else:
                k += 1
        return 글[시작:k]
    끝 = len(글)
    for 표 in ("\n", "}}"):
        j = 글.find(표, 시작)
        if j >= 0:
            끝 = min(끝, j)
    return 글[시작:끝]


def _칸쪼개기(글):
    """중첩 안의 | 는 건드리지 않고 바깥의 | 로만 자른다."""
    조각, 깊이, 시작, k = [], 0, 0, 0
    while k < len(글):
        if 글.startswith("[[", k) or 글.startswith("{{", k):
            깊이 += 1
            k += 2
            continue
        if 글.startswith("]]", k) or 글.startswith("}}", k):
            깊이 -= 1
            k += 2
            continue
        if 깊이 == 0 and 글[k] == "|":
            조각.append(글[시작:k])
            시작 = k + 1
        k += 1
    조각.append(글[시작:])
    return 조각


def _평문(글):
    """위키 문법을 걷어낸다. 남는 것은 사람이 읽는 문장이다."""
    글 = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", 글, flags=re.S)
    글 = re.sub(r"\{\{[^{}]*\}\}", "", 글)
    글 = re.sub(r"\[\[[^\[\]|]*\|([^\[\]|]*)\]\]", r"\1", 글)   # [[가|나]] -> 나
    글 = re.sub(r"\[\[([^\[\]|]*)\]\]", r"\1", 글)              # [[가]]   -> 가
    글 = re.sub(r"<[^>]+>", "", 글)
    글 = 글.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", 글).strip()


def _캡션(칸들):
    """그림 문법의 칸에서 사람이 읽는 말만 남긴다.

    [[파일:x.jpg|thumb|300px|<캡션>]] 에서 앞의 것들은 배치 지시다.
    마지막에 남는 것이 캡션인데, 캡션이 아예 없는 그림도 많다."""
    남은 = [c.strip() for c in 칸들 if c.strip() and not _꾸밈말.match(c.strip())]
    return _평문(남은[-1]) if 남은 else ""


_그림쓰임 = re.compile(
    r"(?i)(\[\[\s*)?(?:파일|그림|file|image)\s*:\s*"
    r"([^|\]\n}]+?\.(?:jpe?g|png|gif|webp))")
# 틀(인포박스)에서는 접두어 없이 값으로만 온다: | 그림 = 이름.jpg
# 토막글에는 이 형태밖에 없는 경우가 많다. 캡션은 옆 칸(그림설명)에 있다.
_틀그림 = re.compile(
    r"(?im)^[ \t]*\|[ \t]*(?:그림|사진|이미지|image|photo|사진이름|그림이름)"
    r"[ \t]*\d*[ \t]*=[ \t]*(?:\[\[)?[ \t]*(?:파일|그림|file|image)?[ \t]*:?[ \t]*"
    r"([^|\n\[\]]+?\.(?:jpe?g|png|gif|webp))")
# = 뒤를 \s* 로 받으면 안 된다. \s 에 줄바꿈이 들어 있어서 빈 칸을
# 지나 다음 줄을 통째로 삼킨다 — "|그림설명 = " 다음 줄의 "|본명 = ..." 이
# 캡션으로 들어와 낱말 빈도 1위(50회)를 먹었다.
_틀캡션 = re.compile(
    r"(?im)^[ \t]*\|[ \t]*(?:그림설명|사진설명|캡션|caption|설명)"
    r"[ \t]*\d*[ \t]*=[ \t]*([^|\n]+)$")


def 그림찾기(제목):
    """문서 하나에서 (파일이름, 캡션) 을 뽑는다. 아직 내려받지 않는다.

    svg 는 안 받는다. 대개 로고·도표라 사진과 국소 통계가 아예 다른데,
    섞으면 시각 어휘가 무엇 때문에 늘어난 것인지 못 가린다."""
    r = _부르기(action="parse", page=제목, prop="wikitext", redirects=1)
    본문 = r.get("parse", {}).get("wikitext", {}).get("*", "")
    # 각주는 캡션 한가운데에 끼어든다. 사람이 읽는 캡션이 아니므로 먼저 뺀다.
    본문 = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", 본문, flags=re.S)
    나온것, 본것 = [], set()
    for m in _그림쓰임.finditer(본문):
        이름 = m.group(2).strip().replace("_", " ")
        if _잡그림.search(이름) or 이름 in 본것:
            continue
        본것.add(이름)
        칸 = _칸쪼개기(_칸들(본문, m.end(), bool(m.group(1))))
        나온것.append({"파일": 이름, "캡션": _캡션(칸[1:])})
    틀설명 = _틀캡션.search(본문)
    틀설명 = _평문(틀설명.group(1)) if 틀설명 else ""
    for m in _틀그림.finditer(본문):
        이름 = m.group(1).strip().replace("_", " ")
        if _잡그림.search(이름) or 이름 in 본것:
            continue
        본것.add(이름)
        나온것.append({"파일": 이름, "캡션": 틀설명})
    # 캡션 있는 것을 앞에 둔다. 수를 자를 때 재료가 되는 쪽이 남게.
    나온것.sort(key=lambda x: not x["캡션"])
    return 나온것


def _접두어없이(제목):
    """'파일:x.jpg' -> 'x.jpg'.

    한국어 위키는 File: 로 물어도 파일: 로 정규화해 돌려준다. 이걸 안 벗기면
    이름이 안 맞아 주소를 못 찾는다 — 그림을 9장 찾아 놓고 0장을 받았다."""
    return re.sub(r"(?i)^\s*(?:file|image|파일|그림)\s*:\s*", "", 제목).strip()


def 주소들(이름들, 너비=480):
    """파일 이름 -> 내려받을 주소. 원본이 아니라 축소본을 받는다.

    원본은 한 장에 수 MB 씩 가는데 그림.py 가 어차피 256px 로 줄여 본다.
    남의 서버에서 받는 것이니 필요한 만큼만 받는다."""
    주소 = {}
    for k in range(0, len(이름들), 40):
        묶음 = 이름들[k:k + 40]
        r = _부르기(action="query", prop="imageinfo", iiprop="url|mime|size",
                    iiurlwidth=너비, titles="|".join("File:" + x for x in 묶음))
        for 쪽 in r.get("query", {}).get("pages", {}).values():
            정보 = (쪽.get("imageinfo") or [{}])[0]
            이름 = _접두어없이(쪽.get("title", ""))
            u = 정보.get("thumburl") or 정보.get("url")
            # 150px 도 안 되는 것은 내용 그림이 아니라 표식이다
            if u and 정보.get("width", 0) >= 150:
                주소[이름] = u
    return 주소


def _받은것():
    """이미 받은 파일 이름. 두 번 받지 않으려고."""
    경로 = os.path.join(그림밖, 목록)
    if not os.path.exists(경로):
        return set()
    본것 = set()
    with open(경로, encoding="utf-8") as f:
        for 줄 in f:
            try:
                본것.add(json.loads(줄)["원본"])
            except Exception:
                pass
    return 본것


def 그림고르기(제목, 파일들=None, 본것=(), 최대=5):
    """무엇을 받을지만 정한다. 위키텍스트 한 번(캡션용). 아직 안 받는다.

    캡션은 위키텍스트에서, 파일 목록은 prop=images 에서 온다. 둘이 다르다 —
    요즘 틀은 그림을 위키데이터에서 끌어와서 위키텍스트에 파일 이름이 아예
    없는 문서가 많다. 목록에만 있는 그림은 캡션 없이 받는다. 힙스에는
    캡션이 필요 없고, 공기를 셀 때 캡션 있는 것만 쓰면 된다.

    한 문서에서 많이 받지 않는다(최대 5장). 같은 문서의 그림은 서로 닮아서
    — 고양이 문서의 고양이 12장 — 몇 문서가 표본을 먹으면 무늬가 포화한
    것처럼 보인다. 힙스가 재려는 것이 바로 그 포화라서 치명적이다."""
    쌍 = 그림찾기(제목)
    if 파일들 is None:
        파일들 = 그림있나([제목]).get(제목, [])
    적힌것 = {x["파일"] for x in 쌍}
    쌍 += [{"파일": f, "캡션": ""} for f in 파일들 if f not in 적힌것]
    return [x for x in 쌍 if x["파일"] not in 본것][:최대]


def 내려받기(제목, 쌍, 주소, 본것):
    """정해진 것을 받아 목록에 적는다. API 는 안 부른다(주소는 이미 있다)."""
    os.makedirs(그림밖, exist_ok=True)
    센것 = 0
    with open(os.path.join(그림밖, 목록), "a", encoding="utf-8") as f:
        for x in 쌍:
            u = 주소.get(x["파일"])
            if not u:
                continue
            안전 = re.sub(r'[\\/:*?"<>|]', "", x["파일"]).replace(" ", "_")[:120]
            if not _그림확장.search(안전):
                안전 += ".jpg"
            try:
                req = urllib.request.Request(u, headers=헤더)
                덩이 = urllib.request.urlopen(req, timeout=30).read()
            except Exception:
                continue
            with open(os.path.join(그림밖, 안전), "wb") as g:
                g.write(덩이)
            f.write(json.dumps({"파일": 안전, "캡션": x["캡션"], "문서": 제목,
                                "원본": x["파일"], "주소": u,
                                "받은날": time.strftime("%Y-%m-%d")},
                               ensure_ascii=False) + "\n")
            본것.add(x["파일"])
            센것 += 1
            time.sleep(0.1)          # 그림 서버는 API 와 다른 곳이라 가볍게만
    return 센것


def 그림받기(제목, 최대=5, 본것=None, 파일들=None):
    """문서 하나. 고르고 주소를 묻고 받는다. -> 받은 수"""
    본것 = _받은것() if 본것 is None else 본것
    쌍 = 그림고르기(제목, 파일들, 본것, 최대)
    if not 쌍:
        return 0
    return 내려받기(제목, 쌍, 주소들([x["파일"] for x in 쌍]), 본것)


def 아무문서(수=10):
    """아무 문서나. 범용을 재려면 표본도 범용이어야 한다 —
    한 도메인에서만 모으면 무늬가 포화하는 것이 당연해서 아무것도 안 말해준다."""
    제목 = []
    while len(제목) < 수:
        r = _부르기(action="query", list="random", rnnamespace=0,
                    rnlimit=min(50, 수 - len(제목)))
        새것 = [x["title"] for x in r.get("query", {}).get("random", [])]
        if not 새것:
            break
        제목 += 새것
    return 제목[:수]


if __name__ == "__main__":
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--찾기" in sys.argv:
        if not 인자:
            print("사용법: python 위키.py --찾기 <말>")
            sys.exit(1)
        for x in 찾기(인자[0]):
            print("  %-34s %5d 단어" % (x["제목"], x["단어수"]))
        sys.exit(0)

    if "--그림" in sys.argv:
        # 그림은 자료/그림/ 으로 따로 간다. 글과 섞지 않는다 —
        # 짓기.py 가 도는 자료/웹 에 캡션이 끼면 기존 그래프가 흔들린다.
        본것, 모두, 문서수 = _받은것(), 0, 0
        시작 = time.time()

        def 모으기(표):
            """뭉치 하나를 통째로. 주소는 뭉치 전체를 한 번에 묻는다.

            문서마다 따로 물으면 호출이 문서 수만큼 늘어난다. 그렇게 했다가
            429 를 맞았고 백오프가 42초까지 갔다."""
            고른것 = {}
            for 제목 in 표:
                try:
                    고른것[제목] = 그림고르기(제목, 표[제목], 본것)
                except Exception as e:
                    print("X   %-40s %s: %s" % (제목[:40], type(e).__name__, e))
            전체 = [x["파일"] for v in 고른것.values() for x in v]
            if not 전체:
                return 0
            주소 = 주소들(전체)
            return sum(내려받기(제목, 쌍, 주소, 본것)
                       for 제목, 쌍 in 고른것.items())

        if "--아무거나" in sys.argv:
            # 1500개를 다 모은 뒤 시작하면 진행이 안 보이고 중간 결과도 안 쌓인다.
            # 실제로 5분 46초 동안 출력 0바이트였다. 50개씩 끊어서 바로 받는다.
            목표 = int(인자[0]) if 인자 and 인자[0].isdigit() else 30
            본것 = _받은것()
            물어본수 = 0
            while 물어본수 < 목표:
                뭉치 = 아무문서(min(50, 목표 - 물어본수))
                if not 뭉치:
                    break
                물어본수 += len(뭉치)
                표 = 그림있나(뭉치)
                문서수 += len(표)
                모두 += 모으기(표)
                지난 = time.time() - 시작
                print("문서 %4d/%d  그림있음 %3d  받음 %4d장  %4.1f분  (%.0f장/분)"
                      % (물어본수, 목표, 문서수, 모두, 지난 / 60,
                         모두 / max(지난 / 60, 0.01)))
        elif 인자:
            제목들 = []
            for 말 in 인자:
                후보 = 찾기(말, 1)
                if 후보:
                    제목들.append(후보[0]["제목"])
                else:
                    print("?  %-16s 찾지 못했다" % 말)
            표 = 그림있나(제목들)
            모두 += 모으기(표)
            print("받음 %d장" % 모두)
        else:
            print("사용법: python 위키.py --그림 <말>...  |  --그림 --아무거나 <수>")
            sys.exit(1)

        print()
        print("자료/그림/ 에 %d 장. 캡션이 같이 갔다 — 그것이 라벨이다." % 모두)
        print("  python 그림.py --갈림     # 비트를 얼마로 잡나")
        print("  python 그림.py --힙스     # 시각 어휘가 포화하는지 잰다")
        sys.exit(0)

    if not 인자:
        print(__doc__)
        sys.exit(1)
    for 말 in 인자:
        try:
            후보 = 찾기(말, 1)
            if not 후보:
                print("?  %-16s 찾지 못했다" % 말)
                continue
            제목 = 후보[0]["제목"]
            본문 = 받기(제목)
            if not 본문:
                print("?  %-16s 본문이 비었다 (%s)" % (말, 제목))
                continue
            경로 = 저장(제목, 본문)
            print("OK %-16s -> %s  (%d자)" % (말, 경로, len(본문)))
        except Exception as e:
            print("X  %-16s %s: %s" % (말, type(e).__name__, e))
        time.sleep(0.4)
    print()
    print("자료로 들어갔을 뿐 그래프가 된 것은 아니다. 다음 중 하나를 한다:")
    print("  python 짓기.py 자료/웹 --out 웹그래프.json")
    print("  python engine.py --mine <그래프.kg> 자료/웹/위키_....txt")
