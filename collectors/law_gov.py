# -*- coding: utf-8 -*-
"""법제처 국가법령정보 공동활용 API 로 원문을 받는다.

위키문헌은 판본에 조문이 빠져 있다(형법 75개 누락 확인). 이쪽이 완전하다.

준비:
    open.law.go.kr 에서 활용 신청 -> OC 값(신청 이메일의 @ 앞부분)을 받는다
    set LAW_OC=hong          (Windows)
    export LAW_OC=hong       (bash)

사용:
    python law_gov.py 형법 민법 근로기준법
    python law_gov.py --검색 개인정보          # 법령 이름 찾기
"""
import os
import re
import sys
import time
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

outside = "법지식"
precedent_outside = "판례"
OC = os.environ.get("LAW_OC", "").strip()
header = {"User-Agent": "lawgraph/0.1"}


def call(target, **argv):
    if not OC:
        raise SystemExit("LAW_OC 환경변수가 없습니다. open.law.go.kr 신청 후\n"
                         "  set LAW_OC=<신청 이메일의 @ 앞부분>")
    base = ("http://www.law.go.kr/DRF/law%s.do"
            % ("Search" if target.lower().endswith("search") else "Service"))
    argv = dict(OC=OC, type="XML", **argv)
    argv.setdefault("target", "prec" if target.startswith("prec") else "law")
    url = base + "?" + urllib.parse.urlencode(argv, encoding="utf-8")
    req = urllib.request.Request(url, headers=header)
    whole_text = urllib.request.urlopen(req, timeout=30).read()
    return ET.fromstring(whole_text)


def find(name, num=10):
    root = call("search", query=name, display=num)
    emitted = []
    for law in root.iter("law"):
        def value(t):
            e = law.find(t)
            return (e.text or "").strip() if e is not None else ""
        emitted.append({"이름": value("법령명한글"), "MST": value("법령일련번호"),
                     "시행": value("시행일자"), "구분": value("법령구분명")})
    return [x for x in emitted if x["MST"]]


def receive(MST):
    root = call("law", MST=MST)
    name = root.findtext(".//법령명_한글") or root.findtext(".//법령명한글") or MST
    line = []
    for art in root.iter("조문단위"):
        idx = (art.findtext("조문번호") or "").strip()
        title = (art.findtext("조문제목") or "").strip()
        body = (art.findtext("조문내용") or "").strip()
        head = "제%s조%s" % (idx, "(%s)" % title if title else "")
        body = re.sub(r"^제\s*%s\s*조[^)]*\)?\s*" % re.escape(idx), "", body)
        line.append("%s %s" % (head, body))
        for para in art.iter("항"):
            t = (para.findtext("항내용") or "").strip()
            if t:
                line.append(t)
            for subclause in para.iter("호"):
                t = (subclause.findtext("호내용") or "").strip()
                if t:
                    line.append(t)
    return name.strip(), "\n".join(line)


def find_precedent(phrase, num=100, page=1):
    """참조조문에 이 조문이 걸린 판례 목록. target=prec.

    판례가 왜 필요한가: 엣지 방향을 사람이 12만 번 정하지 않으려면
    기계가 채점할 수 있어야 하는데, lint/진단은 구조만 봐서 150건 중
    1건밖에 못 걸렀다. 판례는 (사실 -> 법원의 결론) 라벨이다.
    엣지를 넣고 빼며 실제 판결과 일치하는지 재면 그게 채점기가 된다."""
    root = call("precSearch", query=phrase, display=num, page=page, search=2)
    emitted = []
    for p in root.iter("prec"):
        def value(t):
            e = p.find(t)
            return (e.text or "").strip() if e is not None else ""
        emitted.append({"ID": value("판례일련번호"), "사건명": value("사건명"),
                     "사건번호": value("사건번호"), "법원": value("법원명"),
                     "선고일": value("선고일자"), "종류": value("사건종류명")})
    return [x for x in emitted if x["ID"]]


def receive_precedent(ID):
    """판례 하나. 판시사항/판결요지/참조조문/전문."""
    root = call("prec", ID=ID)
    def value(t):
        e = root.find(".//" + t)
        return re.sub(r"<[^>]+>", " ", (e.text or "")).strip() if e is not None else ""
    return {"ID": ID, "사건명": value("사건명"), "사건번호": value("사건번호"),
            "법원": value("법원명"), "선고일": value("선고일자"),
            "판시사항": value("판시사항"), "판결요지": value("판결요지"),
            "참조조문": value("참조조문"), "전문": value("판례내용")}


def gather_precedent(phrase, article, max_n=200, notice=None):
    """본문 검색으로 받아 참조조문으로 거른다.

    검색 목록에는 참조조문이 없어서 본문을 받아봐야 안다. 본문 검색만
    믿으면 '형법 제21조'라는 글자가 스친 아동복지법 판례가 딸려온다 —
    실제로 첫 결과가 그랬다. 참조조문에 걸린 것만 채점 데이터가 된다."""
    collection, seen, page = [], set(), 1
    while len(seen) < max_n:
        listing = find_precedent(phrase, num=100, page=page)
        if not listing:
            break
        for x in listing:
            if x["ID"] in seen or len(seen) >= max_n:
                continue
            seen.add(x["ID"])
            try:
                d = receive_precedent(x["ID"])
            except Exception:
                continue
            if article in "".join(d["참조조문"].split()):
                collection.append(d)
                if notice:
                    notice(len(seen), len(collection), d)
            time.sleep(0.25)
        page += 1
    return collection, len(seen)


def save_precedent(article, precedents):
    """한 조문의 판례를 jsonl 한 파일로. 채점용 데이터라 원문 그대로 둔다."""
    os.makedirs(precedent_outside, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|\s]", "", article)
    path = os.path.join(precedent_outside, "판례_%s.jsonl" % safe)
    with open(path, "w", encoding="utf-8") as f:
        for d in precedents:
            f.write(json.dumps(d, ensure_ascii=False) + chr(10))
    return path


def save(name, body):
    os.makedirs(outside, exist_ok=True)
    safe = re.sub(r"[\/:*?\"<>|]", "", name).replace(" ", "_")
    path = os.path.join(outside, "법령_%s.txt" % safe)
    art = sorted({int(x) for x in re.findall(r"제\s*(\d+)\s*조", body)})
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 출처: 법제처 국가법령정보 %s\n# 조문 %d개 (제%d조까지)\n\n"
                % (name, len(art), max(art) if art else 0))
        f.write(body + "\n")
    return path, len(art), len(body)


if __name__ == "__main__":
    if "--판례" in sys.argv:
        argv = [a for a in sys.argv[1:] if not a.startswith("--")]
        if not argv:
            print("사용법: python law_gov.py --판례 \"형법 제21조\" [검색어] [최대]")
            print('  예:  python law_gov.py --판례 "형법 제21조" 정당방위 200')
            sys.exit(1)
        article = argv[0]
        phrase = argv[1] if len(argv) > 1 else article
        max_n = int(argv[2]) if len(argv) > 2 else 200
        flat = "".join(article.split())
        def notice(whole_text, salvaged, d):
            print("   + %s %s %s" % (d["사건번호"], d["법원"], d["사건명"][:34]))
        try:
            collection, scan = gather_precedent(phrase, flat, max_n, notice)
            path = save_precedent(article, collection)
            print("OK %s -> %s" % (article, path))
            print("   %d건 훑어 참조조문에 걸린 %d건 (%.0f%%)"
                  % (scan, len(collection), 100 * len(collection) / max(scan, 1)))
        except Exception as e:
            print("X  %s %s: %s" % (article, type(e).__name__, e))
        sys.exit(0)

    if "--검색" in sys.argv:
        for x in find(sys.argv[sys.argv.index("--검색") + 1]):
            print("  %-28s MST=%-10s 시행 %s  %s"
                  % (x["이름"], x["MST"], x["시행"], x["구분"]))
        sys.exit(0)
    laws = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not laws:
        print(__doc__)
        sys.exit(1)
    success = 0
    for law in laws:
        try:
            # 부분문자열 검색이라 '상법' 이 '보상법' 뒤로 밀린다. 넓게 받아 거른다.
            result = find(law, 100)
            wish = law.replace(" ", "")
            # 이름이 정확히 같은 것만 고른다. '상법' 으로 검색하면
            # '1980년해직공무원의보상등에관한특별조치법' 이 1위로 나온다.
            exacts = [x for x in result if x["이름"].replace(" ", "") == wish]
            if not exacts:
                exacts = [x for x in result if x["구분"] == "법률"
                        and wish in x["이름"].replace(" ", "")]
            if not exacts:
                print("?  %-14s 정확히 일치하는 법령 없음 (후보: %s)"
                      % (law, ", ".join(x["이름"] for x in result[:3])))
                continue
            exact_ = max(exacts, key=lambda x: x["시행"])      # 가장 최근 시행
            name, body = receive(exact_["MST"])
            path, article_count, char = save(name, body)
            print("OK %-14s -> %s  (조문 %d개 · %d자)" % (law, path, article_count, char))
            success += 1
        except Exception as e:
            print("X  %-14s %s: %s" % (law, type(e).__name__, e))
        time.sleep(0.5)
    print("\n%d/%d 확보" % (success, len(laws)))
