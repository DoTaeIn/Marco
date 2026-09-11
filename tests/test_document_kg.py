# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path
import zipfile
from unittest.mock import patch

import document_kg
import engine


class DocumentKnowledgeGraphTest(unittest.TestCase):
    def setUp(self):
        self.units = [document_kg.Unit(
            "slide.1",
            "그래프는 노드와 엣지로 구성된 지식 표현이다. 먼저 원문에서 위치가 확인된 주장을 고른다. 원문에 근거가 없으면 추가 자료를 요청해야 한다.",
            "그래프 생성 원칙",
        )]

    def test_extracts_typed_claims_with_source_locations(self):
        analysis = document_kg.analyze_units("시험 자료", self.units)
        self.assertEqual(analysis["status"], "sufficient")
        self.assertEqual(len(analysis["claims"]), 3)
        self.assertEqual(analysis["claims"][0]["kind"], "definition")
        self.assertEqual({claim["location"] for claim in analysis["claims"]}, {"slide.1"})

    def test_insufficient_input_does_not_become_knowledge(self):
        analysis = document_kg.analyze_units("짧은 자료", [document_kg.Unit("p.1", "짧은 설명입니다.")])
        self.assertEqual(analysis["status"], "insufficient")
        with self.assertRaises(document_kg.DocumentKGError):
            document_kg.to_graph(analysis)

    def test_reads_text_boxes_from_a_real_pptx_container(self):
        slide = '''<?xml version="1.0" encoding="UTF-8"?>
        <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
               xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>그래프는 노드와 엣지로 구성된 지식 표현이다.</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
        </p:sld>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lecture.pptx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", slide)
            title, units, warnings = document_kg.read_pptx(path)
        self.assertEqual(title, "lecture")
        self.assertEqual(warnings, [])
        self.assertEqual([(unit.location, unit.text) for unit in units],
                         [("slide.1", "그래프는 노드와 엣지로 구성된 지식 표현이다.")])

    def test_pptx_media_is_bound_to_its_slide_location(self):
        slide = '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><a:blip r:embed="rId7"/></p:sld>'''
        rels = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId7" Target="../media/image1.png"/></Relationships>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visual.pptx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", slide)
                archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
                archive.writestr("ppt/media/image1.png", b"not-a-real-image")
            report = {"location": "", "facts": [], "warnings": []}
            with patch("document_kg.document_visual.analyze_image", side_effect=lambda _, location: {**report, "location": location}):
                reports, warnings = document_kg._pptx_visuals(path)
        self.assertEqual(warnings, [])
        self.assertEqual([item["location"] for item in reports], ["slide.1.figure.1"])

    def test_generated_graph_answers_only_from_document_evidence(self):
        analysis = document_kg.analyze_units("시험 자료", self.units)
        graph = document_kg.to_graph(analysis)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.graph.json"
            path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            loaded = engine.load(str(path))
            session = engine.Session(loaded)
            answer = session.reply("그래프는 노드와 엣지로 구성된 지식 표현이다.")
            self.assertEqual(session.verdict, "인정", answer)
            self.assertIn("그래프는 노드와 엣지", answer)
            unknown = engine.Session(loaded).reply("문서에 없는 양자 암호의 안전성을 확정해줘")
            self.assertIn("근거", unknown)


if __name__ == "__main__":
    unittest.main()
