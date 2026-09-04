# -*- coding: utf-8 -*-
"""PDF/PPTX 원문을 검증 가능한 지식 그래프로 바꾸는 보수적 수집기.

문서의 문장을 '이해한 척' 요약하지 않는다. 페이지/슬라이드 위치가 있는 문장만
주장 후보로 삼고, 정의·인과·절차·한계·근거 관계를 구분한다. 그림·표·스캔처럼
텍스트로 읽히지 않는 부분, 대명사가 풀리지 않는 부분은 그래프에 사실로 넣지 않고
검토 항목으로 남긴다.

    python document_kg.py paper.pdf --out /private/tmp/paper.graph.json
    python document_kg.py lecture.pptx --report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from xml.etree import ElementTree

import document_visual


class DocumentKGError(RuntimeError):
    pass


@dataclass(frozen=True)
class Unit:
    location: str
    text: str
    heading: str = ""


_sentence_end = re.compile(r"(?<=[.!?])\s+|(?<=다)\s+|(?<=요)\s+|(?<=니다)\s+")
_space = re.compile(r"\s+")
_definition = re.compile(r"^(.{2,45}?)(?:은|는|이란|란)\s+(.{8,260}?)(?:이다|입니다|을 말한다|를 뜻한다|을 의미한다)[.]?$")
_cause = re.compile(r"(.{2,110}?)(?:때문에|로 인해|에 의해|원인으로|causes?|leads? to|results? in)\s+(.{2,160})", re.I)
_procedure = re.compile(r"(?:먼저|다음|이후|마지막|단계|절차|방법|해야|해야 한다|해야 합니다|first|then|finally)\b", re.I)
_limitation = re.compile(r"(?:한계|제한|제약|불확실|추가 연구|일반화|주의|그러나|다만|may |might |cannot |limitation)", re.I)
_evidence = re.compile(r"(?:결과|실험|분석|조사|표\s*\d|그림\s*\d|Figure\s*\d|Table\s*\d|we found|results? show)", re.I)
_pronoun = re.compile(r"^(?:이것|그것|이는|이는|해당|이러한|그러한|this|that|these|those)\b", re.I)


def _clean(text: str) -> str:
    return _space.sub(" ", text or "").strip()


def _pdf_to_text_binary() -> str | None:
    """시스템 또는 번들 Poppler의 pdftotext를 찾는다.

    서버의 기본 Python에 PDF 라이브러리가 없어도 작동하도록 외부 Python 의존성은
    두지 않는다. 번들 런타임 경로는 없는 환경에서는 단순히 후보에서 제외한다.
    """
    candidates = [os.environ.get("NAI_PDFTOTEXT"), shutil.which("pdftotext"),
                  "/Users/dotaein/.cache/codex-runtimes/codex-primary-runtime/"
                  "dependencies/native/poppler/poppler/bin/pdftotext"]
    return next((path for path in candidates if path and os.path.isfile(path) and os.access(path, os.X_OK)), None)


def read_pdf(path: str | os.PathLike) -> tuple[str, list[Unit], list[str]]:
    path = Path(path)
    command = _pdf_to_text_binary()
    if not command:
        raise DocumentKGError("PDF 텍스트 추출기(pdftotext)를 찾지 못했습니다")
    with tempfile.TemporaryDirectory(prefix="nai-document-pdf-") as td:
        text_path = Path(td) / "document.txt"
        result = subprocess.run([command, "-layout", str(path), str(text_path)],
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise DocumentKGError("PDF 텍스트를 읽지 못했습니다: " + (result.stderr.strip() or "변환 실패"))
        raw = text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""
    pages = raw.split("\f")
    units = [Unit("p.%d" % (index + 1), _clean(page))
             for index, page in enumerate(pages) if _clean(page)]
    warnings = []
    if not units or sum(len(unit.text) for unit in units) < 120:
        warnings.append("PDF에서 충분한 텍스트를 읽지 못했습니다. 스캔본·그림·표 중심 문서는 OCR/시각 해석이 필요합니다.")
    return path.stem, units, warnings


def _pptx_text(xml: bytes) -> str:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return ""
    return _clean(" ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t")))


def read_pptx(path: str | os.PathLike) -> tuple[str, list[Unit], list[str]]:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            slides = sorted((name for name in archive.namelist()
                             if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                            key=lambda name: int(re.search(r"\d+", name).group()))
            units = []
            for index, name in enumerate(slides, 1):
                text = _pptx_text(archive.read(name))
                if text:
                    # 첫 구절은 슬라이드 제목의 후보로만 사용한다. 실제 본문과
                    # 섞어 요약하지 않으며 출처는 언제나 슬라이드 번호다.
                    heading = text.split(" ", 12)[0] if len(text) < 60 else text[:60]
                    units.append(Unit("slide.%d" % index, text, heading))
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocumentKGError("PPTX를 읽지 못했습니다: %s" % exc) from exc
    warnings = []
    if not units:
        warnings.append("PPTX에서 텍스트 상자를 읽지 못했습니다. 이미지·도표만 있는 슬라이드는 현재 사실 그래프로 만들지 않습니다.")
    return path.stem, units, warnings


def read_document(path: str | os.PathLike) -> tuple[str, list[Unit], list[str]]:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".pptx":
        return read_pptx(path)
    raise DocumentKGError("지원 형식은 PDF와 PPTX입니다: %s" % suffix)


def _pdftoppm_binary() -> str | None:
    candidates = [shutil.which("pdftoppm"),
                  "/Users/dotaein/.cache/codex-runtimes/codex-primary-runtime/"
                  "dependencies/bin/override/pdftoppm"]
    return next((item for item in candidates if item and os.path.isfile(item) and os.access(item, os.X_OK)), None)


def _pdfimages_binary() -> str | None:
    candidates = [shutil.which("pdfimages"),
                  "/Users/dotaein/.cache/codex-runtimes/codex-primary-runtime/"
                  "dependencies/native/poppler/poppler/bin/pdfimages"]
    return next((item for item in candidates if item and os.path.isfile(item) and os.access(item, os.X_OK)), None)


def _figure_pages(units: list[Unit]) -> list[int]:
    """캡션이 있는 쪽과 텍스트가 거의 없는 쪽만 보아, 본문 전체 OCR 반복을 피한다."""
    selected = []
    marker = re.compile(r"(?:\bfig(?:ure)?\.?\s*\d|\bchart\b|\bgraph\b|\btable\s*\d|그림\s*\d|도표|그래프|표\s*\d)", re.I)
    for unit in units:
        match = re.fullmatch(r"p\.(\d+)", unit.location)
        if match and (marker.search(unit.text) or len(unit.text) < 300):
            selected.append(int(match.group(1)))
    # 원문에 그림 표지가 없더라도 첫 페이지만은 시각 분석한다. 제목 그림/초록
    # 도표를 놓치지 않되, 긴 논문을 무제한 OCR하지 않는 상한이다.
    if not selected and units:
        selected.append(1)
    return selected[:24]


def _pdf_visuals(path: Path, units: list[Unit]) -> tuple[list[dict], list[str]]:
    renderer = _pdftoppm_binary()
    if not renderer:
        return [], ["PDF 페이지 렌더러를 찾지 못해 그림·도표 분석을 보류했습니다"]
    reports, warnings = [], []
    pages = _figure_pages(units)
    def allowed_fact_kinds(page: int | None) -> set[str]:
        """텍스트 PDF의 그림은 캡션과 맞는 구조만 사실로 승격한다.

        OCR 문구는 이미 추출된 본문과 중복될 수 있고, 논문 도식의 사각형은
        표/막대로 오인되기 쉽다. 스캔본처럼 텍스트가 거의 없을 때만 OCR·객체
        관찰을 허용하고, 텍스트 본문이 있으면 Table/Chart/Graph 표지와 일치하는
        구조만 허용한다.
        """
        unit = next((u for u in units if page and u.location == "p.%d" % page), None)
        if unit is None:
            return set()
        if len(unit.text) < 300:
            return {"visual_text", "chart_structure", "table_structure", "visual_object", "visual_relation"}
        allowed: set[str] = set()
        if re.search(r"\btable\s*\d|표\s*\d", unit.text, re.I):
            allowed.add("table_structure")
        if re.search(r"\b(?:chart|graph)\b|차트|그래프", unit.text, re.I):
            allowed.add("chart_structure")
        return allowed
    # 번들 Poppler가 빈 Fontconfig 경로를 상속하면 경고를 대량 출력하는
    # macOS 환경이 있다. 시스템 설정을 바꾸지 않고, 프로세스에만 정상 설정을
    # 넘긴다.
    render_env = dict(os.environ)
    fontconfig = "/opt/homebrew/etc/fonts/fonts.conf"
    if os.path.isfile(fontconfig):
        render_env.setdefault("FONTCONFIG_FILE", fontconfig)
    with tempfile.TemporaryDirectory(prefix="nai-document-visual-") as directory:
        # 사진/스캔 그림은 페이지를 다시 렌더링하는 것보다 원본 래스터를 직접
        # 읽어 OCR·객체 검출 정확도를 높인다. 페이지 번호는 pdfimages 목록에서
        # 가능한 범위로 보존하고, 매핑이 안 되면 원본 이미지 번호로 명시한다.
        extractor = _pdfimages_binary()
        extracted_pages: set[int] = set()
        if extractor:
            prefix = Path(directory) / "embedded"
            listing = subprocess.run([extractor, "-list", str(path)], capture_output=True, text=True,
                                     timeout=60, env=render_env)
            page_rows = []
            if listing.returncode == 0:
                for line in listing.stdout.splitlines():
                    match = re.match(r"\s*(\d+)\s+(\d+)\s+image\b", line)
                    if match:
                        page_rows.append(int(match.group(1)))
            proc = subprocess.run([extractor, "-png", str(path), str(prefix)], capture_output=True, text=True,
                                  timeout=120, env=render_env)
            if proc.returncode == 0:
                files = sorted(Path(directory).glob("embedded-*.png"))[:48]
                for index, image in enumerate(files):
                    page = page_rows[index] if index < len(page_rows) else None
                    location = "p.%d.embedded_image.%d" % (page, index + 1) if page else "pdf.embedded_image.%d" % (index + 1)
                    try:
                        report = document_visual.analyze_image(image, location)
                        # 텍스트 레이어가 있는 PDF에서 원본 그림 OCR은 같은
                        # 문장을 두 번째 사실로 만드는 경우가 많다. 그림의 구조
                        # (표/차트/객체)만 보존하고 OCR 문구는 review로 보낸다.
                        report["allowed_fact_kinds"] = allowed_fact_kinds(page)
                        reports.append(report)
                        if page:
                            extracted_pages.add(page)
                    except (document_visual.VisualError, OSError) as exc:
                        warnings.append("%s 시각 분석 실패: %s" % (location, exc))
        for page in pages:
            # 임베디드 래스터가 있는 페이지도 벡터 도표가 있을 수 있다. 캡션
            # 표지가 있을 때만 렌더링을 병행해 불필요한 중복을 줄인다.
            if page in extracted_pages and not re.search(r"(?:\bfig|\bchart|\bgraph|그림|도표|그래프)", next((u.text for u in units if u.location == "p.%d" % page), ""), re.I):
                continue
            prefix = Path(directory) / ("page-%d" % page)
            proc = subprocess.run([renderer, "-f", str(page), "-l", str(page), "-r", "180", "-png",
                                   str(path), str(prefix)], capture_output=True, text=True, timeout=90,
                                  env=render_env)
            # Poppler 버전에 따라 page-1-1.png 또는 page-1-01.png을 쓴다.
            # 접두사와 확장자로 찾되 이 렌더 호출이 만든 단일 파일만 허용한다.
            images = sorted(Path(directory).glob(prefix.name + "-*.png"))
            image = images[0] if len(images) == 1 else None
            if proc.returncode or image is None:
                warnings.append("p.%d 렌더링 실패: %s" % (page, proc.stderr.strip() or "출력 이미지 없음"))
                continue
            try:
                report = document_visual.analyze_image(image, "p.%d.figure" % page)
                report["allowed_fact_kinds"] = allowed_fact_kinds(page)
                reports.append(report)
            except (document_visual.VisualError, OSError) as exc:
                warnings.append("p.%d 시각 분석 실패: %s" % (page, exc))
    return reports, warnings


def _pptx_visuals(path: Path) -> tuple[list[dict], list[str]]:
    reports, warnings = [], []
    try:
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="nai-pptx-visual-") as directory:
            # 슬라이드의 rId -> ppt/media 파일 관계를 따라간다. zip 안의 미디어
            # 순서는 슬라이드 순서와 무관하므로 번호만 출처로 쓰면 안 된다.
            media_locations: dict[str, list[str]] = {}
            for slide_name in archive.namelist():
                slide_match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", slide_name)
                if not slide_match:
                    continue
                slide_number = slide_match.group(1)
                rel_name = "ppt/slides/_rels/slide%s.xml.rels" % slide_number
                if rel_name not in archive.namelist():
                    continue
                try:
                    rel_root = ElementTree.fromstring(archive.read(rel_name))
                    targets = {item.attrib.get("Id"): item.attrib.get("Target", "") for item in rel_root}
                    slide_root = ElementTree.fromstring(archive.read(slide_name))
                except ElementTree.ParseError:
                    warnings.append("slide.%s 관계 XML을 읽지 못했습니다" % slide_number)
                    continue
                ordinal = 0
                for node in slide_root.iter():
                    if not node.tag.endswith("}blip"):
                        continue
                    relation = next((value for key, value in node.attrib.items() if key.endswith("}embed")), None)
                    target = targets.get(relation, "")
                    if not target:
                        continue
                    # ../media/image1.png을 zip 내부 절대 상대 경로로 정규화한다.
                    media_name = posixpath.normpath(str(PurePosixPath("ppt/slides") / target))
                    ordinal += 1
                    media_locations.setdefault(media_name, []).append("slide.%s.figure.%d" % (slide_number, ordinal))
            media = [name for name in archive.namelist()
                     if re.fullmatch(r"ppt/media/[^/]+\.(?:png|jpe?g|gif|bmp|tiff?)", name, re.I)]
            for number, name in enumerate(media[:48], 1):
                target = Path(directory) / Path(name).name
                target.write_bytes(archive.read(name))
                try:
                    locations = media_locations.get(name) or ["pptx.media.%d" % number]
                    for location in locations:
                        reports.append(document_visual.analyze_image(target, location))
                except (document_visual.VisualError, OSError) as exc:
                    warnings.append("%s 시각 분석 실패: %s" % (name, exc))
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append("PPTX 미디어를 읽지 못했습니다: %s" % exc)
    return reports, warnings


def visual_observations(path: str | os.PathLike, units: list[Unit]) -> tuple[list[dict], list[str]]:
    """텍스트가 아닌 그림에서 온 관찰만 반환한다. 실패는 문서 전체 실패가 아니다."""
    source = Path(path)
    if source.suffix.lower() == ".pdf":
        return _pdf_visuals(source, units)
    if source.suffix.lower() == ".pptx":
        return _pptx_visuals(source)
    return [], []


def split_sentences(text: str) -> list[str]:
    out = []
    for raw in _sentence_end.split(_clean(text)):
        sentence = _clean(raw)
        if 20 <= len(sentence) <= 380:
            out.append(sentence)
    return out


def classify(sentence: str) -> str | None:
    """문장 자체가 말하는 관계만 보수적으로 분류한다."""
    if _definition.match(sentence):
        return "definition"
    if _cause.search(sentence):
        return "causal"
    if _procedure.search(sentence):
        return "procedure"
    if _limitation.search(sentence):
        return "limitation"
    if _evidence.search(sentence):
        return "evidence"
    # 문장 종결이 있는 서술은 사실 후보이지만, 질문/명령/제목 조각은 제외한다.
    if sentence.endswith(("다.", "니다.", ".")) and not sentence.endswith("?"):
        return "statement"
    return None


def _claim_id(index: int) -> str:
    return "주장_%03d" % index


def analyze_units(title: str, units: list[Unit], warnings: list[str] | None = None) -> dict:
    warnings = list(warnings or [])
    claims, review = [], []
    for unit in units:
        for sentence in split_sentences(unit.text):
            kind = classify(sentence)
            if not kind:
                continue
            if _pronoun.search(sentence):
                review.append({"location": unit.location, "text": sentence,
                               "reason": "앞 문맥을 잃은 지시어가 있어 독립 주장으로 확정하지 않았습니다"})
                continue
            claims.append({"id": _claim_id(len(claims) + 1), "kind": kind,
                           "text": sentence, "location": unit.location,
                           "heading": unit.heading})
    # 같은 위치의 같은 문장은 한번만 둔다. 반복 슬라이드/머리말은 그래프를
    # 부풀릴 뿐 새로운 근거가 아니다.
    seen, unique = set(), []
    for claim in claims:
        key = (claim["location"], claim["text"])
        if key not in seen:
            seen.add(key); unique.append(claim)
    claims = unique
    kinds = {kind: sum(c["kind"] == kind for c in claims)
             for kind in ("definition", "causal", "procedure", "limitation", "evidence", "statement")}
    sufficient = len(claims) >= 3 and not any("충분한 텍스트" in warning for warning in warnings)
    if not sufficient:
        warnings.append("검증 가능한 독립 주장이 3개 미만입니다. 그래프를 저장하지 않고 원문·OCR·설명자료를 더 요청해야 합니다.")
    return {"format": "nai-document-understanding", "version": 1, "title": title,
            "units": [asdict(unit) for unit in units], "claims": claims,
            "review": review, "warnings": list(dict.fromkeys(warnings)),
            "coverage": kinds, "status": "sufficient" if sufficient else "insufficient"}


def add_visual_claims(analysis: dict, visuals: list[dict], warnings: list[str] | None = None) -> dict:
    """검증된 이미지 관찰만 기존 주장 목록에 더한다.

    장면 분류의 낮은 신뢰도나 OCR 한 번의 추정은 사실 노드가 아니라 review에
    남긴다. 따라서 시각 분석이 있어도 원문 근거 기준은 느슨해지지 않는다.
    """
    analysis["visuals"] = visuals
    analysis["warnings"].extend(warnings or [])
    claims, review = analysis["claims"], analysis["review"]
    for visual in visuals:
        if not visual.get("facts"):
            review.append({"location": visual.get("location", "image"), "text": "",
                           "reason": "이미지에서 그래프에 넣을 만큼 검증된 텍스트·차트 구조를 찾지 못했습니다"})
        for fact in visual.get("facts", []):
            allowed = visual.get("allowed_fact_kinds")
            if allowed is not None and fact.get("kind") not in allowed:
                review.append({"location": fact.get("location") or visual.get("location", "image"),
                               "text": fact.get("text", ""),
                               "reason": "PDF 본문·캡션과 독립적으로 검증되지 않은 시각 관찰이라 사실 노드에 넣지 않았습니다"})
                continue
            if float(fact.get("confidence", 0)) < .70:
                continue
            claims.append({"id": _claim_id(len(claims) + 1), "kind": fact["kind"],
                           "text": fact["text"], "location": fact.get("location") or visual.get("location", "image"),
                           "heading": "시각 분석", "confidence": fact["confidence"],
                           "method": fact["method"]})
    analysis["coverage"]["visual"] = sum(1 for claim in claims if claim["kind"].startswith(("visual_", "chart_")))
    analysis["warnings"] = list(dict.fromkeys(analysis["warnings"]))
    # 텍스트가 부족한 문서도 독립적인 시각 관찰 세 개가 있을 때만 충분으로 승격한다.
    if analysis["status"] == "insufficient" and len(claims) >= 3 and not any("충분한 텍스트" in warning for warning in analysis["warnings"]):
        analysis["status"] = "sufficient"
        analysis["warnings"] = [warning for warning in analysis["warnings"]
                                if not warning.startswith("검증 가능한 독립 주장")]
    return analysis


def to_graph(analysis: dict) -> dict:
    """분석이 충분할 때만 engine.load가 읽는 JSON 그래프로 바꾼다."""
    if analysis.get("status") != "sufficient":
        raise DocumentKGError("문서 이해가 충분하지 않아 그래프를 만들지 않습니다")
    title = analysis["title"]
    goal = "문서지식_" + title
    common = {goal: ["%s 문서에서 위치가 확인된 주장" % title]}
    cases, edges, sources = {}, [], {}
    for claim in analysis["claims"]:
        evidence = "근거_" + claim["id"]
        concept = claim["id"]
        cases[evidence] = [claim["text"]]
        common[concept] = [claim["text"]]
        edges.extend([[evidence, "증명", concept], [concept, "충족", goal]])
        sources[evidence] = {"document": title, "location": claim["location"],
                             "heading": claim.get("heading") or "", "kind": claim["kind"]}
    dialogues = {"B2": "이 문서의 근거와 연결되지 않습니다.",
                 "B2_강등": "이 문서의 근거와 연결되지 않습니다. 위치나 용어를 더 알려 주세요.",
                 "A": "문서의 어느 주장인지 더 구체적으로 알려 주세요.",
                 "근거없음": "문서에서 이 주장을 뒷받침하는 위치를 찾지 못했습니다.",
                 "인정": "{claim}", "인정_반격": "{claim} 다만, 문서의 한계와 반대 근거도 확인해야 합니다.",
                 "C": "{ev}만으로는 {claim}을 확정할 수 없습니다.",
                 "B1": "{claim}은 관련 있지만 문서 안의 직접 근거가 부족합니다.",
                 "미지": "문서에서 확인 가능한 근거를 찾지 못했습니다. 해당 페이지·슬라이드나 원문을 더 알려 주세요."}
    return {"역할": "문서 근거 지식 그래프", "목표": goal,
            "임계값": {"A_MIN": 0.42, "OK_MIN": 0.58}, "이름말": "문장",
            "전진관계": ["증명", "충족"], "부정관계": ["부정"],
            "공통층": common, "사례층": cases, "무관층": {}, "엣지": edges,
            "개념엣지": [], "수치조건": {}, "대사": dialogues, "출처": sources,
            "문서분석": {key: analysis[key] for key in ("coverage", "review", "warnings")}}


def learn(path: str | os.PathLike, output: str | os.PathLike | None = None) -> dict:
    title, units, warnings = read_document(path)
    analysis = analyze_units(title, units, warnings)
    visuals, visual_warnings = visual_observations(path, units)
    analysis = add_visual_claims(analysis, visuals, visual_warnings)
    result = {"analysis": analysis, "graph": None, "saved": None}
    if analysis["status"] != "sufficient":
        return result
    graph = to_graph(analysis)
    result["graph"] = graph
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp-%d" % os.getpid())
        try:
            temp.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temp, target)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        result["saved"] = str(target)
    return result


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document")
    parser.add_argument("--out", help="충분히 이해한 경우에만 쓸 graph JSON 경로")
    parser.add_argument("--report", action="store_true", help="분석 보고서를 JSON으로 출력")
    args = parser.parse_args(argv)
    try:
        result = learn(args.document, args.out)
    except DocumentKGError as exc:
        print("문서 그래프 오류: %s" % exc, file=sys.stderr)
        return 2
    if args.report:
        print(json.dumps(result["analysis"], ensure_ascii=False, indent=2))
    elif result["saved"]:
        print("그래프 저장: %s · 주장 %d개" % (result["saved"], len(result["analysis"]["claims"])))
    else:
        print("그래프를 만들지 않았습니다: " + " / ".join(result["analysis"]["warnings"]))
    return 0 if result["analysis"]["status"] == "sufficient" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
