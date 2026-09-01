# -*- coding: utf-8 -*-
"""위키문헌에서 법령 원문을 받아 법지식/ 에 저장한다.

법제처(law.go.kr)는 본문을 JS 로 그리므로 껍데기만 온다. 공개 API 는 키가 필요하다.
위키문헌은 action=raw 로 원문이 그대로 오고 라이선스도 자유롭다.

    python 법수집.py 대한민국헌법 형법 민법
    python 법수집.py --목록          # 받을 수 있는 법령 찾기
"""
import os
import re
import sys
import time
import json
import urllib.parse
import urllib.request

OUTPUT_DIR = "법지식"
HEADERS = {"User-Agent": "Mnemosyne-lawgraph/0.1 (research; contact via github)"}


def fetch(title, retries=2):
    url = ("https://ko.wikisource.org/w/index.php?title="
           + urllib.parse.quote(title.replace(" ", "_")) + "&action=raw")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except Exception:
            if attempt == retries:
                raise
            time.sleep(1.5 * (attempt + 1))


def search(query, limit=10):
    """위키문헌 검색. 법령 이름 규칙이 '형법 (대한민국, 제N호)' 처럼 제각각이라
    바로 받기 전에 실제 문서명을 찾는다."""
    url = ("https://ko.wikisource.org/w/api.php?action=query&list=search&srsearch="
           + urllib.parse.quote(query) + "&srlimit=%d&format=json" % limit)
    req = urllib.request.Request(url, headers=HEADERS)
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
    return [item["title"] for item in data["query"]["search"]]


def select_current_law(query):
    """검색 결과에서 '그 법의 현행 조문 문서' 로 보이는 것을 고른다."""
    results = search(query)
    normalized_name = query.replace(" ", "")
    candidates = [item for item in results if item.replace(" ", "").startswith(normalized_name)]
    # 글로벌 세계 대백과사전 같은 해설 문서는 조문이 아니다
    candidates = [item for item in candidates if "/" not in item and "백과" not in item]
    if not candidates:
        return query
    numbered_results = [(int(re.search(r"제(\d+)호", item).group(1)), item) for item in candidates
                        if re.search(r"제(\d+)호", item)]
    if numbered_results:
        return max(numbered_results)[1]
    return min(candidates, key=len)


def follow_redirects(title, depth=4):
    """넘겨주기와 '버전 목록' 페이지를 모두 통과해 조문이 있는 문서까지 간다.

    위키문헌 법령은 세 형태가 섞여 있다:
      1) 조문이 바로 있는 문서
      2) #넘겨주기
      3) '대한민국헌법' 처럼 개정 이력을 나열하는 목록 페이지
    3번을 리다이렉트로 착각하면 조문 0개가 나온다. 현행판을 골라 들어간다."""
    text = fetch(title)
    for _ in range(depth):
        match = re.match(r"#(?:넘겨주기|REDIRECT)\s*\[\[(.+?)\]\]", text.strip(), re.I)
        if match:
            title = match.group(1).split("|")[0].split("#")[0]
            text = fetch(title)
            continue
        if len(re.findall(r"제\s*\d+\s*조", text)) >= 3:
            break
        # 목록 페이지: "현행" 이라고 적힌 줄의 링크, 없으면 호수가 가장 큰 것
        link_pattern = re.compile(r"\[\[([^\]|]+)\]\]")
        current_lines = [line for line in text.splitlines() if "현행" in line and link_pattern.search(line)]
        candidates = re.findall(r"\[\[([^\]|]*?\(제(\d+)호\))\]\]", text)
        if current_lines:
            title = link_pattern.search(current_lines[0]).group(1)
        elif candidates:
            title = max(candidates, key=lambda item: int(item[1]))[0]
        else:
            break
        text = fetch(title)
    return title, text


def clean_wikitext(wikitext):
    """위키 문법을 걷어내고 조문만 남긴다. 원문을 바꾸지 않는 선에서만."""
    t = re.sub(r"\{\{[^{}]*\}\}", "", wikitext)          # 틀
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)              # 중첩 한 겹 더
    t = re.sub(r"</?blockquote>", "", t)
    t = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", t)
    t = re.sub(r"\[\[([^\]]+)\]\]", r"\1", t)
    t = re.sub(r"'''?", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&quot;", '"'),
                 ("&nbsp;", " ")):
        t = t.replace(a, b)
    lines = []
    for line in t.splitlines():
        line = line.strip()
        if not line or line.startswith(("|", "!")):
            continue
        if line.startswith("="):                          # == 제1장 ... ==
            lines.append("\n" + line.strip("= ").strip())
            continue
        if line.startswith(("*", ":", ";")):
            line = line.lstrip("*:; ")
        if line:
            lines.append(line)
    return "\n".join(lines).strip() + "\n"


def output_path(title):
    name = re.sub(r"\s*\(제?\d+호\)\s*$", "", title).strip()
    name = re.sub(r"[\/:*?\"<>|]", "", name).replace(" ", "_")
    return os.path.join(OUTPUT_DIR, "법령_%s.txt" % name)


def download_law(title):
    try:
        actual_title, wikitext = follow_redirects(title)
    except Exception:
        actual_title, wikitext = None, ""          # 그 이름의 문서가 아예 없다 -> 검색으로
    if len(re.findall(r"제\s*\d+\s*조", wikitext)) < 3:
        candidate = select_current_law(title)
        if candidate != title or actual_title is None:
            actual_title, wikitext = follow_redirects(candidate)
    body = clean_wikitext(wikitext)
    articles = sorted({int(item) for item in re.findall(r"제\s*(\d+)\s*조", body)})
    if len(articles) < 3:
        return None, "조문이 %d개뿐 — 문서가 아니거나 형식이 다릅니다" % len(articles)
    path = output_path(actual_title)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        f.write("# 출처: 위키문헌 %s\n# 조문 %d개 (제%d조까지)\n\n"
                % (actual_title, len(articles), max(articles)))
        file.write(body)
    return path, "조문 %d개 · %d자" % (len(articles), len(body))


if __name__ == "__main__":
    laws = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
    if not laws:
        print(__doc__)
        sys.exit(1)
    successes = 0
    for law in laws:
        try:
            path, message = download_law(law)
        except Exception as error:
            print("X  %-16s %s: %s" % (law, type(error).__name__, error))
            continue
        if path:
            print("OK %-16s -> %s  (%s)" % (law, path, message))
            successes += 1
        else:
            print("?  %-16s %s" % (law, message))
        time.sleep(0.6)                                # 위키문헌에 대한 예의
    print("\n%d/%d 확보" % (successes, len(laws)))
