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

밖 = "법지식"
헤더 = {"User-Agent": "Mnemosyne-lawgraph/0.1 (research; contact via github)"}


def 받기(제목, 재시도=2):
    url = ("https://ko.wikisource.org/w/index.php?title="
           + urllib.parse.quote(제목.replace(" ", "_")) + "&action=raw")
    for 회 in range(재시도 + 1):
        try:
            req = urllib.request.Request(url, headers=헤더)
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except Exception as e:
            if 회 == 재시도:
                raise
            time.sleep(1.5 * (회 + 1))


def 찾기(질의, 수=10):
    """위키문헌 검색. 법령 이름 규칙이 '형법 (대한민국, 제N호)' 처럼 제각각이라
    바로 받기 전에 실제 문서명을 찾는다."""
    url = ("https://ko.wikisource.org/w/api.php?action=query&list=search&srsearch="
           + urllib.parse.quote(질의) + "&srlimit=%d&format=json" % 수)
    req = urllib.request.Request(url, headers=헤더)
    d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
    return [x["title"] for x in d["query"]["search"]]


def 고르기(질의):
    """검색 결과에서 '그 법의 현행 조문 문서' 로 보이는 것을 고른다."""
    결과 = 찾기(질의)
    이름 = 질의.replace(" ", "")
    딱 = [t for t in 결과 if t.replace(" ", "").startswith(이름)]
    # 글로벌 세계 대백과사전 같은 해설 문서는 조문이 아니다
    딱 = [t for t in 딱 if "/" not in t and "백과" not in t]
    if not 딱:
        return 질의
    호수 = [(int(re.search(r"제(\d+)호", t).group(1)), t) for t in 딱
            if re.search(r"제(\d+)호", t)]
    if 호수:
        return max(호수)[1]
    return min(딱, key=len)


def 따라가기(제목, 깊이=4):
    """넘겨주기와 '버전 목록' 페이지를 모두 통과해 조문이 있는 문서까지 간다.

    위키문헌 법령은 세 형태가 섞여 있다:
      1) 조문이 바로 있는 문서
      2) #넘겨주기
      3) '대한민국헌법' 처럼 개정 이력을 나열하는 목록 페이지
    3번을 리다이렉트로 착각하면 조문 0개가 나온다. 현행판을 골라 들어간다."""
    본 = 받기(제목)
    for _ in range(깊이):
        m = re.match(r"#(?:넘겨주기|REDIRECT)\s*\[\[(.+?)\]\]", 본.strip(), re.I)
        if m:
            제목 = m.group(1).split("|")[0].split("#")[0]
            본 = 받기(제목)
            continue
        if len(re.findall(r"제\s*\d+\s*조", 본)) >= 3:
            break
        # 목록 페이지: "현행" 이라고 적힌 줄의 링크, 없으면 호수가 가장 큰 것
        링크 = re.compile(r"\[\[([^\]|]+)\]\]")
        현행줄 = [l for l in 본.splitlines() if "현행" in l and 링크.search(l)]
        후보 = re.findall(r"\[\[([^\]|]*?\(제(\d+)호\))\]\]", 본)
        if 현행줄:
            제목 = 링크.search(현행줄[0]).group(1)
        elif 후보:
            제목 = max(후보, key=lambda t: int(t[1]))[0]
        else:
            break
        본 = 받기(제목)
    return 제목, 본


def 정리(위키):
    """위키 문법을 걷어내고 조문만 남긴다. 원문을 바꾸지 않는 선에서만."""
    t = re.sub(r"\{\{[^{}]*\}\}", "", 위키)          # 틀
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
    줄 = []
    for l in t.splitlines():
        l = l.strip()
        if not l or l.startswith(("|", "!")):
            continue
        if l.startswith("="):                          # == 제1장 ... ==
            줄.append("\n" + l.strip("= ").strip())
            continue
        if l.startswith(("*", ":", ";")):
            l = l.lstrip("*:; ")
        if l:
            줄.append(l)
    return "\n".join(줄).strip() + "\n"


def 파일명(제목):
    이름 = re.sub(r"\s*\(제?\d+호\)\s*$", "", 제목).strip()
    이름 = re.sub(r"[\/:*?\"<>|]", "", 이름).replace(" ", "_")
    return os.path.join(밖, "법령_%s.txt" % 이름)


def 하나(제목):
    try:
        실제, 위키 = 따라가기(제목)
    except Exception:
        실제, 위키 = None, ""          # 그 이름의 문서가 아예 없다 -> 검색으로
    if len(re.findall(r"제\s*\d+\s*조", 위키)) < 3:
        후보 = 고르기(제목)
        if 후보 != 제목 or 실제 is None:
            실제, 위키 = 따라가기(후보)
    본문 = 정리(위키)
    조 = sorted({int(x) for x in re.findall(r"제\s*(\d+)\s*조", 본문)})
    if len(조) < 3:
        return None, "조문이 %d개뿐 — 문서가 아니거나 형식이 다릅니다" % len(조)
    경로 = 파일명(실제)
    os.makedirs(밖, exist_ok=True)
    with open(경로, "w", encoding="utf-8") as f:
        f.write("# 출처: 위키문헌 %s\n# 조문 %d개 (제%d조까지)\n\n"
                % (실제, len(조), max(조)))
        f.write(본문)
    return 경로, "조문 %d개 · %d자" % (len(조), len(본문))


if __name__ == "__main__":
    법들 = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not 법들:
        print(__doc__)
        sys.exit(1)
    성공 = 0
    for 법 in 법들:
        try:
            경로, 말 = 하나(법)
        except Exception as e:
            print("X  %-16s %s: %s" % (법, type(e).__name__, e))
            continue
        if 경로:
            print("OK %-16s -> %s  (%s)" % (법, 경로, 말))
            성공 += 1
        else:
            print("?  %-16s %s" % (법, 말))
        time.sleep(0.6)                                # 위키문헌에 대한 예의
    print("\n%d/%d 확보" % (성공, len(법들)))
