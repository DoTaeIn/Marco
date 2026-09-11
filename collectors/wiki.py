# -*- coding: utf-8 -*-
"""위키백과에서 글을 받아 data/ 에 넣는다. 검색은 답하는 도구가 아니라 자료를 늘리는 도구다.

    python wiki.py 정당방위 명예훼손        # 받아서 data/웹/ 에 저장
    python wiki.py --찾기 저작권             # 무엇이 있는지 먼저 본다
    python wiki.py --그림 정당방위 편의점    # 그림 + 캡션 -> data/그림/
    python wiki.py --그림 --아무거나 200     # 아무 문서 200개에서. 범용 표본

받은 글은 그래프에 바로 들어가지 않는다. data/ 에 놓이고, 거기서부터는
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

outside = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "웹")
header = {"User-Agent": "Objection/0.1 (https://github.com/DoTaeIn/Objection) python-urllib"}
API = "https://ko.wikipedia.org/w/api.php?"


_between = float(os.environ.get("위키_간격", "1.0"))   # API 호출 최소 간격(초)
_last = [0.0]


def _take_break():
    """남의 서버다. 간격은 부르는 쪽마다 지키는 게 아니라 여기서 한 번 지킨다."""
    remaining = _between - (time.time() - _last[0])
    if remaining > 0:
        time.sleep(remaining)
    _last[0] = time.time()


def _call(**argv):
    """API 한 번. 429/503 이면 물러났다가 다시 묻는다.

    남의 서버다. 그림을 받으려면 문서 하나에 여러 번 불러야 해서 글만 받을
    때보다 훨씬 빨리 벽에 닿는다 — 무작위 20개에서 8개 만에 429 가 났다.
    maxlag 는 위키미디어가 정한 예의다. 복제 지연이 크면 우리가 기다린다."""
    argv.setdefault("format", "json")
    argv.setdefault("maxlag", 5)
    url = API + urllib.parse.urlencode(argv, encoding="utf-8")
    req = urllib.request.Request(url, headers=header)
    pause = 2.0
    for _ in range(8):
        _take_break()
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503):
                raise
            wait = e.headers.get("Retry-After")
            lock = float(wait) if wait and wait.isdigit() else pause
            print("   (%d. %.0f초 쉼)" % (e.code, lock), file=sys.stderr)
            time.sleep(lock)
            pause = min(pause * 2, 30)
            continue
        # maxlag 초과는 200 으로 오고 error 안에 들어 있다
        if r.get("error", {}).get("code") == "maxlag":
            print("   (maxlag. %.0f초 쉼)" % pause, file=sys.stderr)
            time.sleep(pause)
            pause = min(pause * 2, 30)
            continue
        return r
    raise RuntimeError("위키가 계속 물러나라고 한다. 나중에 다시.")


def has_images(titles):
    """제목 50개씩 묶어 '그림이 있는 문서' 만 걸러낸다.

    무작위 문서는 대부분 토막글이라 그림이 없다. 그런데 캡션을 얻으려면
    문서마다 위키텍스트를 따로 불러야 한다 — 없는 문서까지 부르면 호출이
    몇 배가 되고 그래서 429 를 맞았다. 이 한 번으로 50개를 걸러낸다."""
    present_ones = {}
    for k in range(0, len(titles), 50):
        group = titles[k:k + 50]
        r = _call(action="query", prop="images", imlimit="max",
                    titles="|".join(group), redirects=1)
        for page in r.get("query", {}).get("pages", {}).values():
            to_write = [_no_prefix(x["title"]) for x in page.get("images", [])]
            to_write = [x for x in to_write
                    if _IMAGE_EXTS.search(x) and not _misc_image.search(x)]
            if to_write:
                present_ones[page["title"]] = to_write
    return present_ones


def find(phrase, num=8):
    """-> [{제목, 단어수}]"""
    r = _call(action="query", list="search", srsearch=phrase, srlimit=num)
    return [{"제목": x["title"], "단어수": x.get("wordcount", 0)}
            for x in r.get("query", {}).get("search", [])]


def receive(title):
    """문서 하나의 본문. 위키 문법을 걷어낸 평문."""
    r = _call(action="query", prop="extracts", titles=title,
                explaintext=1, exsectionformat="plain", redirects=1)
    page = list(r.get("query", {}).get("pages", {}).values())
    if not page or "extract" not in page[0]:
        return None
    body = page[0]["extract"]
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body or None


def save(title, body):
    os.makedirs(outside, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "", title).replace(" ", "_")
    path = os.path.join(outside, "위키_%s.txt" % safe)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 출처: 위키백과 「%s」 (https://ko.wikipedia.org/wiki/%s)\n"
                % (title, urllib.parse.quote(title.replace(" ", "_"))))
        f.write("# 받은 날: %s\n\n" % time.strftime("%Y-%m-%d"))
        f.write(body + "\n")
    return path


# ───────────────────────────── 그림 ─────────────────────────────
# 그림만 받아서는 아무것도 못 짓는다. 시각 단어를 낱말에 잇는 것은 학습이
# 아니라 공기(共起)인데, 그 짝을 공짜로 만들어 주는 것이 캡션이다.
# 그래서 그림과 캡션은 반드시 한 줄로 묶어서 받는다 —
# 사람이 라벨을 달지 않는다는 뜻이기도 하다. 캡션이 이미 라벨이다.

image_outside = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "그림")
listing = "그림목록.jsonl"

# 문서마다 딸려오는 장식들. 내용과 아무 상관이 없는데 모든 문서에 똑같이
# 들어가서, 그대로 두면 그 무늬가 모든 낱말과 공기하는 것으로 세어진다.
_misc_image = re.compile(
    r"(?i)(commons|wiki[a-z]*-logo|logo|icon|아이콘|ambox|question[_ ]book|"
    r"symbol|stub|스텁|edit-|padlock|crystal|nuvola|folder|button|blank|"
    r"spacer|arrow|flag[_ ]of|국기)")
_IMAGE_EXTS = re.compile(r"(?i)\.(jpe?g|png|gif|webp)$")
_modifier = re.compile(
    r"(?i)^(thumb|thumbnail|섬네일|썸네일|frame|frameless|border|right|left|"
    r"center|centre|none|가운데|오른쪽|왼쪽|upright(=[\d.]+)?|"
    r"\d+\s*x?\s*\d*\s*px|alt=.*|link=.*|lang=.*|page=.*|class=.*|"
    r"baseline|middle|sub|super|top|bottom|text-top|text-bottom)$")


def _slots(txt, start, brackets):
    """파일 이름 뒤에 붙은 칸(|thumb|300px|캡션)을 잘라 온다.

    그림이 쓰이는 자리가 세 가지인데 끝나는 표가 다르다.
      [[파일:x.jpg|thumb|캡션]]     -> 짝 맞는 ]] 에서. 캡션 안에 또 [[ ]] 가 있다
      <gallery> 파일:x.jpg|캡션     -> 줄 끝에서
      {{갤러리2 |파일:x.jpg|캡션 }} -> 줄 끝이나 }} 에서
    처음엔 대괄호만 봤더니 CU 문서에서 0장이 나왔다. 그림은 갤러리에 있다."""
    if brackets:
        depth, k = 1, start
        while k < len(txt):
            if txt.startswith("[[", k):
                depth += 1
                k += 2
            elif txt.startswith("]]", k):
                depth -= 1
                if depth == 0:
                    return txt[start:k]
                k += 2
            else:
                k += 1
        return txt[start:k]
    end = len(txt)
    for table in ("\n", "}}"):
        j = txt.find(table, start)
        if j >= 0:
            end = min(end, j)
    return txt[start:end]


def _split_slots(txt):
    """중첩 안의 | 는 건드리지 않고 바깥의 | 로만 자른다."""
    chunk, depth, start, k = [], 0, 0, 0
    while k < len(txt):
        if txt.startswith("[[", k) or txt.startswith("{{", k):
            depth += 1
            k += 2
            continue
        if txt.startswith("]]", k) or txt.startswith("}}", k):
            depth -= 1
            k += 2
            continue
        if depth == 0 and txt[k] == "|":
            chunk.append(txt[start:k])
            start = k + 1
        k += 1
    chunk.append(txt[start:])
    return chunk


def _plaintext(txt):
    """위키 문법을 걷어낸다. 남는 것은 사람이 읽는 문장이다."""
    txt = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", txt, flags=re.S)
    txt = re.sub(r"\{\{[^{}]*\}\}", "", txt)
    txt = re.sub(r"\[\[[^\[\]|]*\|([^\[\]|]*)\]\]", r"\1", txt)   # [[가|나]] -> 나
    txt = re.sub(r"\[\[([^\[\]|]*)\]\]", r"\1", txt)              # [[가]]   -> 가
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = txt.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", txt).strip()


def _caption(slots):
    """그림 문법의 칸에서 사람이 읽는 말만 남긴다.

    [[파일:x.jpg|thumb|300px|<캡션>]] 에서 앞의 것들은 배치 지시다.
    마지막에 남는 것이 캡션인데, 캡션이 아예 없는 그림도 많다."""
    remaining = [c.strip() for c in slots if c.strip() and not _modifier.match(c.strip())]
    return _plaintext(remaining[-1]) if remaining else ""


_image_usage = re.compile(
    r"(?i)(\[\[\s*)?(?:파일|그림|file|image)\s*:\s*"
    r"([^|\]\n}]+?\.(?:jpe?g|png|gif|webp))")
# 틀(인포박스)에서는 접두어 없이 값으로만 온다: | 그림 = 이름.jpg
# 토막글에는 이 형태밖에 없는 경우가 많다. 캡션은 옆 칸(그림설명)에 있다.
_template_image = re.compile(
    r"(?im)^[ \t]*\|[ \t]*(?:그림|사진|이미지|image|photo|사진이름|그림이름)"
    r"[ \t]*\d*[ \t]*=[ \t]*(?:\[\[)?[ \t]*(?:파일|그림|file|image)?[ \t]*:?[ \t]*"
    r"([^|\n\[\]]+?\.(?:jpe?g|png|gif|webp))")
# = 뒤를 \s* 로 받으면 안 된다. \s 에 줄바꿈이 들어 있어서 빈 칸을
# 지나 다음 줄을 통째로 삼킨다 — "|그림설명 = " 다음 줄의 "|본명 = ..." 이
# 캡션으로 들어와 낱말 빈도 1위(50회)를 먹었다.
_template_caption = re.compile(
    r"(?im)^[ \t]*\|[ \t]*(?:그림설명|사진설명|캡션|caption|설명)"
    r"[ \t]*\d*[ \t]*=[ \t]*([^|\n]+)$")


def find_image(title):
    """문서 하나에서 (파일이름, 캡션) 을 뽑는다. 아직 내려받지 않는다.

    svg 는 안 받는다. 대개 로고·도표라 사진과 국소 통계가 아예 다른데,
    섞으면 시각 어휘가 무엇 때문에 늘어난 것인지 못 가린다."""
    r = _call(action="parse", page=title, prop="wikitext", redirects=1)
    body = r.get("parse", {}).get("wikitext", {}).get("*", "")
    # 각주는 캡션 한가운데에 끼어든다. 사람이 읽는 캡션이 아니므로 먼저 뺀다.
    body = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", body, flags=re.S)
    yielded, seen = [], set()
    for m in _image_usage.finditer(body):
        name = m.group(2).strip().replace("_", " ")
        if _misc_image.search(name) or name in seen:
            continue
        seen.add(name)
        slot = _split_slots(_slots(body, m.end(), bool(m.group(1))))
        yielded.append({"파일": name, "캡션": _caption(slot[1:])})
    explain_template = _template_caption.search(body)
    explain_template = _plaintext(explain_template.group(1)) if explain_template else ""
    for m in _template_image.finditer(body):
        name = m.group(1).strip().replace("_", " ")
        if _misc_image.search(name) or name in seen:
            continue
        seen.add(name)
        yielded.append({"파일": name, "캡션": explain_template})
    # 캡션 있는 것을 앞에 둔다. 수를 자를 때 재료가 되는 쪽이 남게.
    yielded.sort(key=lambda x: not x["캡션"])
    return yielded


def _no_prefix(title):
    """'파일:x.jpg' -> 'x.jpg'.

    한국어 위키는 File: 로 물어도 파일: 로 정규화해 돌려준다. 이걸 안 벗기면
    이름이 안 맞아 주소를 못 찾는다 — 그림을 9장 찾아 놓고 0장을 받았다."""
    return re.sub(r"(?i)^\s*(?:file|image|파일|그림)\s*:\s*", "", title).strip()


def urls(names, width=480):
    """파일 이름 -> 내려받을 주소. 원본이 아니라 축소본을 받는다.

    원본은 한 장에 수 MB 씩 가는데 vision.py 가 어차피 256px 로 줄여 본다.
    남의 서버에서 받는 것이니 필요한 만큼만 받는다."""
    url = {}
    for k in range(0, len(names), 40):
        group = names[k:k + 40]
        r = _call(action="query", prop="imageinfo", iiprop="url|mime|size",
                    iiurlwidth=width, titles="|".join("File:" + x for x in group))
        for page in r.get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            name = _no_prefix(page.get("title", ""))
            u = info.get("thumburl") or info.get("url")
            # 150px 도 안 되는 것은 내용 그림이 아니라 표식이다
            if u and info.get("width", 0) >= 150:
                url[name] = u
    return url


def _received():
    """이미 받은 파일 이름. 두 번 받지 않으려고."""
    path = os.path.join(image_outside, listing)
    if not os.path.exists(path):
        return set()
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                seen.add(json.loads(line)["원본"])
            except Exception:
                pass
    return seen


def pick_image(title, files=None, seen=(), max_n=5):
    """무엇을 받을지만 정한다. 위키텍스트 한 번(캡션용). 아직 안 받는다.

    캡션은 위키텍스트에서, 파일 목록은 prop=images 에서 온다. 둘이 다르다 —
    요즘 틀은 그림을 위키데이터에서 끌어와서 위키텍스트에 파일 이름이 아예
    없는 문서가 많다. 목록에만 있는 그림은 캡션 없이 받는다. 힙스에는
    캡션이 필요 없고, 공기를 셀 때 캡션 있는 것만 쓰면 된다.

    한 문서에서 많이 받지 않는다(최대 5장). 같은 문서의 그림은 서로 닮아서
    — 고양이 문서의 고양이 12장 — 몇 문서가 표본을 먹으면 무늬가 포화한
    것처럼 보인다. 힙스가 재려는 것이 바로 그 포화라서 치명적이다."""
    pair = find_image(title)
    if files is None:
        files = has_images([title]).get(title, [])
    recorded = {x["파일"] for x in pair}
    pair += [{"파일": f, "캡션": ""} for f in files if f not in recorded]
    return [x for x in pair if x["파일"] not in seen][:max_n]


def download(title, pair, url, seen):
    """정해진 것을 받아 목록에 적는다. API 는 안 부른다(주소는 이미 있다)."""
    os.makedirs(image_outside, exist_ok=True)
    counted = 0
    with open(os.path.join(image_outside, listing), "a", encoding="utf-8") as f:
        for x in pair:
            u = url.get(x["파일"])
            if not u:
                continue
            safe = re.sub(r'[\\/:*?"<>|]', "", x["파일"]).replace(" ", "_")[:120]
            if not _IMAGE_EXTS.search(safe):
                safe += ".jpg"
            try:
                req = urllib.request.Request(u, headers=header)
                blob = urllib.request.urlopen(req, timeout=30).read()
            except Exception:
                continue
            with open(os.path.join(image_outside, safe), "wb") as g:
                g.write(blob)
            f.write(json.dumps({"파일": safe, "캡션": x["캡션"], "문서": title,
                                "원본": x["파일"], "주소": u,
                                "받은날": time.strftime("%Y-%m-%d")},
                               ensure_ascii=False) + "\n")
            seen.add(x["파일"])
            counted += 1
            time.sleep(0.1)          # 그림 서버는 API 와 다른 곳이라 가볍게만
    return counted


def receive_image(title, max_n=5, seen=None, files=None):
    """문서 하나. 고르고 주소를 묻고 받는다. -> 받은 수"""
    seen = _received() if seen is None else seen
    pair = pick_image(title, files, seen, max_n)
    if not pair:
        return 0
    return download(title, pair, urls([x["파일"] for x in pair]), seen)


def any_doc(num=10):
    """아무 문서나. 범용을 재려면 표본도 범용이어야 한다 —
    한 도메인에서만 모으면 무늬가 포화하는 것이 당연해서 아무것도 안 말해준다."""
    title = []
    while len(title) < num:
        r = _call(action="query", list="random", rnnamespace=0,
                    rnlimit=min(50, num - len(title)))
        fresh = [x["title"] for x in r.get("query", {}).get("random", [])]
        if not fresh:
            break
        title += fresh
    return title[:num]


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--찾기" in sys.argv:
        if not argv:
            print("사용법: python wiki.py --찾기 <말>")
            sys.exit(1)
        for x in find(argv[0]):
            print("  %-34s %5d 단어" % (x["제목"], x["단어수"]))
        sys.exit(0)

    if "--그림" in sys.argv:
        # 그림은 data/그림/ 으로 따로 간다. 글과 섞지 않는다 —
        # 짓기.py 가 도는 data/웹 에 캡션이 끼면 기존 그래프가 흔들린다.
        seen, every, doc_count = _received(), 0, 0
        start = time.time()

        def gather(table):
            """뭉치 하나를 통째로. 주소는 뭉치 전체를 한 번에 묻는다.

            문서마다 따로 물으면 호출이 문서 수만큼 늘어난다. 그렇게 했다가
            429 를 맞았고 백오프가 42초까지 갔다."""
            chosen = {}
            for title in table:
                try:
                    chosen[title] = pick_image(title, table[title], seen)
                except Exception as e:
                    print("X   %-40s %s: %s" % (title[:40], type(e).__name__, e))
            whole = [x["파일"] for v in chosen.values() for x in v]
            if not whole:
                return 0
            url = urls(whole)
            return sum(download(title, pair, url, seen)
                       for title, pair in chosen.items())

        if "--아무거나" in sys.argv:
            # 1500개를 다 모은 뒤 시작하면 진행이 안 보이고 중간 결과도 안 쌓인다.
            # 실제로 5분 46초 동안 출력 0바이트였다. 50개씩 끊어서 바로 받는다.
            goal = int(argv[0]) if argv and argv[0].isdigit() else 30
            seen = _received()
            asked_count = 0
            while asked_count < goal:
                bundle = any_doc(min(50, goal - asked_count))
                if not bundle:
                    break
                asked_count += len(bundle)
                table = has_images(bundle)
                doc_count += len(table)
                every += gather(table)
                last_round = time.time() - start
                print("문서 %4d/%d  그림있음 %3d  받음 %4d장  %4.1f분  (%.0f장/분)"
                      % (asked_count, goal, doc_count, every, last_round / 60,
                         every / max(last_round / 60, 0.01)))
        elif argv:
            titles = []
            for phrase in argv:
                cand = find(phrase, 1)
                if cand:
                    titles.append(cand[0]["제목"])
                else:
                    print("?  %-16s 찾지 못했다" % phrase)
            table = has_images(titles)
            every += gather(table)
            print("받음 %d장" % every)
        else:
            print("사용법: python wiki.py --그림 <말>...  |  --그림 --아무거나 <수>")
            sys.exit(1)

        print()
        print("data/그림/ 에 %d 장. 캡션이 같이 갔다 — 그것이 라벨이다." % every)
        print("  python vision.py --갈림     # 비트를 얼마로 잡나")
        print("  python vision.py --힙스     # 시각 어휘가 포화하는지 잰다")
        sys.exit(0)

    if not argv:
        print(__doc__)
        sys.exit(1)
    for phrase in argv:
        try:
            cand = find(phrase, 1)
            if not cand:
                print("?  %-16s 찾지 못했다" % phrase)
                continue
            title = cand[0]["제목"]
            body = receive(title)
            if not body:
                print("?  %-16s 본문이 비었다 (%s)" % (phrase, title))
                continue
            path = save(title, body)
            print("OK %-16s -> %s  (%d자)" % (phrase, path, len(body)))
        except Exception as e:
            print("X  %-16s %s: %s" % (phrase, type(e).__name__, e))
        time.sleep(0.4)
    print()
    print("자료로 들어갔을 뿐 그래프가 된 것은 아니다. 다음 중 하나를 한다:")
    print("  python build.py data/웹 --out 웹그래프.json")
    print("  python engine.py --mine <그래프.kg> data/웹/위키_....txt")
