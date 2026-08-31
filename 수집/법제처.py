# -*- coding: utf-8 -*-
"""법제처 국가법령정보 공동활용 API 로 원문을 받는다.

위키문헌은 판본에 조문이 빠져 있다(형법 75개 누락 확인). 이쪽이 완전하다.

준비:
    open.law.go.kr 에서 활용 신청 -> OC 값(신청 이메일의 @ 앞부분)을 받는다
    set LAW_OC=hong          (Windows)
    export LAW_OC=hong       (bash)

사용:
    python 법제처.py 형법 민법 근로기준법
    python 법제처.py --검색 개인정보          # 법령 이름 찾기
"""
import os
import re
import sys
import time
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

밖 = "법지식"
판례밖 = "판례"
OC = os.environ.get("LAW_OC", "").strip()
헤더 = {"User-Agent": "lawgraph/0.1"}


def 부르기(target, **인자):
    if not OC:
        raise SystemExit("LAW_OC 환경변수가 없습니다. open.law.go.kr 신청 후\n"
                         "  set LAW_OC=<신청 이메일의 @ 앞부분>")
    바탕 = ("http://www.law.go.kr/DRF/law%s.do"
            % ("Search" if target.lower().endswith("search") else "Service"))
    인자 = dict(OC=OC, type="XML", **인자)
    인자.setdefault("target", "prec" if target.startswith("prec") else "law")
    url = 바탕 + "?" + urllib.parse.urlencode(인자, encoding="utf-8")
    req = urllib.request.Request(url, headers=헤더)
    본 = urllib.request.urlopen(req, timeout=30).read()
    return ET.fromstring(본)


def 찾기(이름, 수=10):
    뿌리 = 부르기("search", query=이름, display=수)
    나옴 = []
    for law in 뿌리.iter("law"):
        def 값(t):
            e = law.find(t)
            return (e.text or "").strip() if e is not None else ""
        나옴.append({"이름": 값("법령명한글"), "MST": 값("법령일련번호"),
                     "시행": 값("시행일자"), "구분": 값("법령구분명")})
    return [x for x in 나옴 if x["MST"]]


def 받기(MST):
    뿌리 = 부르기("law", MST=MST)
    이름 = 뿌리.findtext(".//법령명_한글") or 뿌리.findtext(".//법령명한글") or MST
    줄 = []
    for 조 in 뿌리.iter("조문단위"):
        번호 = (조.findtext("조문번호") or "").strip()
        제목 = (조.findtext("조문제목") or "").strip()
        본문 = (조.findtext("조문내용") or "").strip()
        머리 = "제%s조%s" % (번호, "(%s)" % 제목 if 제목 else "")
        본문 = re.sub(r"^제\s*%s\s*조[^)]*\)?\s*" % re.escape(번호), "", 본문)
        줄.append("%s %s" % (머리, 본문))
        for 항 in 조.iter("항"):
            t = (항.findtext("항내용") or "").strip()
            if t:
                줄.append(t)
            for 호 in 항.iter("호"):
                t = (호.findtext("호내용") or "").strip()
                if t:
                    줄.append(t)
    return 이름.strip(), "\n".join(줄)


def 판례찾기(말, 수=100, 쪽=1):
    """참조조문에 이 조문이 걸린 판례 목록. target=prec.

    판례가 왜 필요한가: 엣지 방향을 사람이 12만 번 정하지 않으려면
    기계가 채점할 수 있어야 하는데, lint/진단은 구조만 봐서 150건 중
    1건밖에 못 걸렀다. 판례는 (사실 -> 법원의 결론) 라벨이다.
    엣지를 넣고 빼며 실제 판결과 일치하는지 재면 그게 채점기가 된다."""
    뿌리 = 부르기("precSearch", query=말, display=수, page=쪽, search=2)
    나옴 = []
    for p in 뿌리.iter("prec"):
        def 값(t):
            e = p.find(t)
            return (e.text or "").strip() if e is not None else ""
        나옴.append({"ID": 값("판례일련번호"), "사건명": 값("사건명"),
                     "사건번호": 값("사건번호"), "법원": 값("법원명"),
                     "선고일": 값("선고일자"), "종류": 값("사건종류명")})
    return [x for x in 나옴 if x["ID"]]


def 판례받기(ID):
    """판례 하나. 판시사항/판결요지/참조조문/전문."""
    뿌리 = 부르기("prec", ID=ID)
    def 값(t):
        e = 뿌리.find(".//" + t)
        return re.sub(r"<[^>]+>", " ", (e.text or "")).strip() if e is not None else ""
    return {"ID": ID, "사건명": 값("사건명"), "사건번호": 값("사건번호"),
            "법원": 값("법원명"), "선고일": 값("선고일자"),
            "판시사항": 값("판시사항"), "판결요지": 값("판결요지"),
            "참조조문": 값("참조조문"), "전문": 값("판례내용")}


def 판례모으기(말, 조문, 최대=200, 알림=None):
    """본문 검색으로 받아 참조조문으로 거른다.

    검색 목록에는 참조조문이 없어서 본문을 받아봐야 안다. 본문 검색만
    믿으면 '형법 제21조'라는 글자가 스친 아동복지법 판례가 딸려온다 —
    실제로 첫 결과가 그랬다. 참조조문에 걸린 것만 채점 데이터가 된다."""
    모음, 본것, 쪽 = [], set(), 1
    while len(본것) < 최대:
        목록 = 판례찾기(말, 수=100, 쪽=쪽)
        if not 목록:
            break
        for x in 목록:
            if x["ID"] in 본것 or len(본것) >= 최대:
                continue
            본것.add(x["ID"])
            try:
                d = 판례받기(x["ID"])
            except Exception:
                continue
            if 조문 in "".join(d["참조조문"].split()):
                모음.append(d)
                if 알림:
                    알림(len(본것), len(모음), d)
            time.sleep(0.25)
        쪽 += 1
    return 모음, len(본것)


def 판례저장(조문, 판례들):
    """한 조문의 판례를 jsonl 한 파일로. 채점용 데이터라 원문 그대로 둔다."""
    os.makedirs(판례밖, exist_ok=True)
    안전 = re.sub(r"[\\/:*?\"<>|\s]", "", 조문)
    경로 = os.path.join(판례밖, "판례_%s.jsonl" % 안전)
    with open(경로, "w", encoding="utf-8") as f:
        for d in 판례들:
            f.write(json.dumps(d, ensure_ascii=False) + chr(10))
    return 경로


def 저장(이름, 본문):
    os.makedirs(밖, exist_ok=True)
    안전 = re.sub(r"[\/:*?\"<>|]", "", 이름).replace(" ", "_")
    경로 = os.path.join(밖, "법령_%s.txt" % 안전)
    조 = sorted({int(x) for x in re.findall(r"제\s*(\d+)\s*조", 본문)})
    with open(경로, "w", encoding="utf-8") as f:
        f.write("# 출처: 법제처 국가법령정보 %s\n# 조문 %d개 (제%d조까지)\n\n"
                % (이름, len(조), max(조) if 조 else 0))
        f.write(본문 + "\n")
    return 경로, len(조), len(본문)


if __name__ == "__main__":
    if "--판례" in sys.argv:
        인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
        if not 인자:
            print("사용법: python 법제처.py --판례 \"형법 제21조\" [검색어] [최대]")
            print('  예:  python 법제처.py --판례 "형법 제21조" 정당방위 200')
            sys.exit(1)
        조문 = 인자[0]
        말 = 인자[1] if len(인자) > 1 else 조문
        최대 = int(인자[2]) if len(인자) > 2 else 200
        납작 = "".join(조문.split())
        def 알림(본, 건진, d):
            print("   + %s %s %s" % (d["사건번호"], d["법원"], d["사건명"][:34]))
        try:
            모음, 훑음 = 판례모으기(말, 납작, 최대, 알림)
            경로 = 판례저장(조문, 모음)
            print("OK %s -> %s" % (조문, 경로))
            print("   %d건 훑어 참조조문에 걸린 %d건 (%.0f%%)"
                  % (훑음, len(모음), 100 * len(모음) / max(훑음, 1)))
        except Exception as e:
            print("X  %s %s: %s" % (조문, type(e).__name__, e))
        sys.exit(0)

    if "--검색" in sys.argv:
        for x in 찾기(sys.argv[sys.argv.index("--검색") + 1]):
            print("  %-28s MST=%-10s 시행 %s  %s"
                  % (x["이름"], x["MST"], x["시행"], x["구분"]))
        sys.exit(0)
    법들 = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not 법들:
        print(__doc__)
        sys.exit(1)
    성공 = 0
    for 법 in 법들:
        try:
            # 부분문자열 검색이라 '상법' 이 '보상법' 뒤로 밀린다. 넓게 받아 거른다.
            결과 = 찾기(법, 100)
            바람 = 법.replace(" ", "")
            # 이름이 정확히 같은 것만 고른다. '상법' 으로 검색하면
            # '1980년해직공무원의보상등에관한특별조치법' 이 1위로 나온다.
            딱들 = [x for x in 결과 if x["이름"].replace(" ", "") == 바람]
            if not 딱들:
                딱들 = [x for x in 결과 if x["구분"] == "법률"
                        and 바람 in x["이름"].replace(" ", "")]
            if not 딱들:
                print("?  %-14s 정확히 일치하는 법령 없음 (후보: %s)"
                      % (법, ", ".join(x["이름"] for x in 결과[:3])))
                continue
            딱 = max(딱들, key=lambda x: x["시행"])      # 가장 최근 시행
            이름, 본문 = 받기(딱["MST"])
            경로, 조수, 글자 = 저장(이름, 본문)
            print("OK %-14s -> %s  (조문 %d개 · %d자)" % (법, 경로, 조수, 글자))
            성공 += 1
        except Exception as e:
            print("X  %-14s %s: %s" % (법, type(e).__name__, e))
        time.sleep(0.5)
    print("\n%d/%d 확보" % (성공, len(법들)))
