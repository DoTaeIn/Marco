# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import document_kg
import document_visual


class DocumentVisualTest(unittest.TestCase):
    def test_same_box_ocr_disagreement_uses_shorter_prefix(self):
        vision = [{"text": "Propagationy", "confidence": 1.0,
                   "box": [.5, .5, .2, .04], "method": "macos_vision"}]
        tess = [{"text": "Propagation.", "confidence": .91,
                 "box": [.5, .5, .2, .04], "method": "tesseract"}]
        words = document_visual._merge_words(vision, tess)
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["text"], "Propagation.")
        self.assertEqual(words[0]["method"], "macos_vision+tesseract")

    def test_colored_bars_and_numeric_ticks_are_a_chart(self):
        pixels = np.full((200, 300, 3), 255, dtype=np.uint8)
        for y, width in ((30, 190), (70, 160), (110, 130), (150, 95)):
            pixels[y:y + 20, 30:30 + width] = [40, 120, 220]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.png"
            Image.fromarray(pixels).save(path)
            words = [{"text": str(value), "confidence": .99, "box": [.01, i / 10, .02, .02], "method": "test"}
                     for i, value in enumerate((0, 10, 20, 30))]
            structure = document_visual._chart_structure(path, words, [])
        self.assertEqual(structure["type"], "bar_chart")
        self.assertGreaterEqual(len(structure["bars"]), 4)

    def test_multiple_thin_colored_series_and_ticks_are_a_line_chart(self):
        image = Image.new("RGB", (320, 200), "white")
        draw = ImageDraw.Draw(image)
        draw.line([(20, 160), (80, 130), (160, 100), (280, 55)], fill=(220, 55, 45), width=3)
        draw.line([(20, 80), (80, 95), (160, 65), (280, 120)], fill=(30, 140, 210), width=3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lines.png"
            image.save(path)
            words = [{"text": str(value), "confidence": .99, "box": [.01, i / 10, .02, .02], "method": "test"}
                     for i, value in enumerate((0, 10, 20, 30))]
            structure = document_visual._line_chart_structure(path, words)
        self.assertEqual(structure["type"], "line_chart")
        self.assertGreaterEqual(structure["series"], 2)

    def test_colored_circle_segments_and_number_are_a_pie_chart(self):
        image = Image.new("RGB", (260, 220), "white")
        draw = ImageDraw.Draw(image)
        bounds = (45, 20, 205, 180)
        draw.pieslice(bounds, 0, 140, fill=(36, 115, 185))
        draw.pieslice(bounds, 140, 260, fill=(240, 160, 35))
        draw.pieslice(bounds, 260, 360, fill=(135, 160, 65))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pie.png"
            image.save(path)
            structure = document_visual._pie_chart_structure(path, [{"text": "30", "confidence": .99, "box": [.5, .5, .1, .1], "method": "test"}])
        self.assertEqual(structure["type"], "pie_chart")
        self.assertGreaterEqual(structure["slices_at_least"], 2)

    def test_line_and_pie_facts_remain_provenance_bound(self):
        analysis = document_kg.analyze_units("도표", [])
        visuals = [{"location": "p.1.figure", "facts": [{
            "kind": "chart_structure", "text": "색상별 얇은 연속선 3개가 확인되는 선 그래프다.",
            "confidence": .78, "method": "pixel_line_structure+ocr"}]},
                   {"location": "p.2.figure", "facts": [{
            "kind": "chart_structure", "text": "최소 3개 범주의 원형 차트다.",
            "confidence": .82, "method": "pixel_pie_structure+ocr"}]}]
        document_kg.add_visual_claims(analysis, visuals)
        self.assertEqual([(claim["location"], claim["kind"]) for claim in analysis["claims"]],
                         [("p.1.figure", "chart_structure"), ("p.2.figure", "chart_structure")])

    def test_grid_lines_form_a_table_with_rows_and_columns(self):
        pixels = np.full((180, 240), 255, dtype=np.uint8)
        for y in (20, 70, 120, 160):
            pixels[y:y + 2, 20:220] = 30
        for x in (20, 90, 160, 220):
            pixels[20:162, x:x + 2] = 30
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.png"
            Image.fromarray(pixels).save(path)
            structure = document_visual._table_structure(path)
        self.assertEqual((structure["type"], structure["rows"], structure["columns"]), ("table", 3, 3))

    def test_visual_facts_are_provenance_bound_graph_claims(self):
        analysis = document_kg.analyze_units("그림만 있는 자료", [])
        visual = {"location": "p.1.figure", "facts": [{
            "kind": "chart_structure", "text": "이미지에는 막대 4개 이상과 수치 눈금이 확인되는 막대 차트가 있다.",
            "confidence": .91, "method": "pixel_structure+ocr"}], "warnings": []}
        document_kg.add_visual_claims(analysis, [visual])
        claim = analysis["claims"][-1]
        self.assertEqual((claim["location"], claim["kind"]), ("p.1.figure", "chart_structure"))
        self.assertEqual(analysis["coverage"]["visual"], 1)

    def test_text_pdf_does_not_promote_unverified_diagram_ocr(self):
        analysis = document_kg.analyze_units("텍스트 PDF", [])
        visual = {"location": "p.3.figure", "allowed_fact_kinds": set(), "facts": [{
            "kind": "visual_text", "text": "이미지에 'Attention'이라는 문구가 보인다.",
            "confidence": .97, "method": "tesseract"}, {
            "kind": "visual_object", "text": "이미지에서 book 객체가 검출된다.",
            "confidence": .77, "method": "yolo_object_detection"}], "warnings": []}
        document_kg.add_visual_claims(analysis, [visual])
        self.assertEqual(analysis["claims"], [])
        self.assertEqual(len(analysis["review"]), 2)

    def test_hand_object_contact_requires_a_confident_wrist_and_box_overlap(self):
        points = [{"x": .0, "y": .0, "confidence": 0.0} for _ in range(17)]
        points[9] = {"x": .46, "y": .51, "confidence": .91}
        people = [{"box": [.2, .1, .3, .7], "confidence": .88, "keypoints": points}]
        objects = [{"label": "cup", "confidence": .86, "box": [.42, .46, .12, .14]},
                   {"label": "person", "confidence": .99, "box": [.2, .1, .3, .7]}]
        contacts = document_visual._hand_object_contacts(people, objects)
        self.assertEqual(len(contacts), 1)
        self.assertEqual((contacts[0]["hand"], contacts[0]["object"]), ("왼손", "cup"))

    def test_pairwise_spatial_relations_keep_direction_and_containment_separate(self):
        objects = [{"label": "person", "confidence": .9, "box": [.05, .10, .20, .60]},
                   {"label": "chair", "confidence": .85, "box": [.60, .30, .30, .50]},
                   {"label": "cup", "confidence": .88, "box": [.67, .42, .04, .08]}]
        relations = document_visual._spatial_relations(objects)
        triples = {(item["subject"], item["relation"], item["object"]) for item in relations}
        self.assertIn(("person", "왼쪽", "chair"), triples)
        self.assertIn(("cup", "안", "chair"), triples)


if __name__ == "__main__":
    unittest.main()
