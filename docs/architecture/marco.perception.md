# `marco.perception`

Written 2026-10-01 against commit `e3a6394`; checked against `547f85b`, where `marco/perception/` is unchanged.

## Purpose

Turn an image from a document into observations that can be checked: OCR words
with boxes, chart and table structure measured from pixels, object boxes, body
keypoints, and spatial relations. The [visual.py](../../marco/perception/visual.py)
docstring: the module does not describe an image in free text, each observation
keeps its image region, confidence and extraction method, and without a
vision-language model it does not state events or causes in a photo as fact.
Each fact candidate `analyze_image` returns carries `location`, `confidence` and
`method` (visual.py:602–638). Goal S4 moved the root files `document_visual`,
`document_vlm`, `document_objects` and `document_pose` here
([target-map.json](target-map.json) `moved_in_s4`), and `document_vision.swift`
with them ([file moves](../ko/2026-09-24-file-moves-goal.md), commit `e4ede99`).
Layer 1 in the target layout; forbidden: graph writes and sentences
([structure-audit.md](structure-audit.md) A6). The fact candidates carry Korean
sentence text (visual.py:606–633).

## Owns

| File | Lines | What |
| --- | --- | --- |
| [`__init__.py`](../../marco/perception/__init__.py) | 0 | empty; exports nothing |
| [visual.py](../../marco/perception/visual.py) | 643 | `analyze_image(path, location)` and `VisualError`. Merges macOS Vision and Tesseract OCR (`_merge_words`); detects bar, line and pie charts and grid tables (`_chart_structure`, `_line_chart_structure`, `_pie_chart_structure`, `_table_structure`); runs the Vision binary and `vlm.py`, `objects.py` and `pose.py` as subprocesses; computes hand–object contact geometry and pairwise spatial relations. Returns `location`, `path`, `words`, `labels`, `structure`, `objects`, `people`, `spatial_relations`, `situations` (status `geometry_observed_not_action`), `semantic_hypothesis`, at most 24 `facts`, and `warnings` |
| [document_vision.swift](../../marco/perception/document_vision.swift) | 62 | macOS Vision bridge: one image in, JSON words with boxes, up to 12 scene labels, and the image size out. `visual.py` compiles it with `swiftc` into `.marco/tools/document_vision` when no executable is there |
| [vlm.py](../../marco/perception/vlm.py) | 84 | subprocess script: asks a local vision-language model for a JSON description of what is visible. `visual.py` returns its output as `semantic_hypothesis`; the one fact candidate drawn from it is a `visual_semantic` line, added only when its `image_type` agrees with a pixel-detected bar chart (visual.py:634–638) |
| [objects.py](../../marco/perception/objects.py) | 47 | subprocess script: object boxes and classes with confidence at least .55 from a YOLO model, as JSON |
| [pose.py](../../marco/perception/pose.py) | 61 | subprocess script: person boxes and keypoints (its docstring: 17 COCO keypoints), normalised, with confidence, as JSON; no posture or action names |

What runs depends on the machine: the Vision binary needs macOS and, to build
it, `swiftc`; Tesseract needs the `tesseract` executable and is run with `-l eng`;
objects, pose and the model need `.venv-vision/bin/python` and weights under
`data/models/`. A missing OCR engine becomes a warning; missing detector or
model files skip that step silently. Neither raises; `VisualError` is raised
only when the image file is missing. A failed detector or model run becomes a
warning. Object detection runs only for images with no chart or table
structure. The model runs only with `NAI_DOCUMENT_VLM=1`, and only for images
with no chart or table structure unless `NAI_DOCUMENT_VLM_ALL=1`. Pose runs
only when object detection found a person.

## Does not own

- **Turning observations into graph claims.** `marco/knowledge/ingest/documents.py`
  calls `analyze_image` and decides which facts become claims
  (`add_visual_claims`).
- **Naming actions.** Contact is geometry only; the docstring of
  `_hand_object_contacts` defers action inference until a verified model and
  data exist.
- **Reading text documents.** PDF and PPTX parsing are in
  `marco/knowledge/ingest/documents.py`.

## Depends on

- `visual.py`: the standard library, `numpy`, `pillow` (`PIL`), and, as
  external programs, `swiftc`, `tesseract` and `.venv-vision/bin/python`.
- `objects.py`, `pose.py`: `ultralytics`, imported inside the function.
- `vlm.py`: `torch`, `pillow`, `transformers`, and one model-specific helper
  package, all imported inside functions.
- No other `marco` package and no root module.

## Public interface

| Name | Imported by | Test |
| --- | --- | --- |
| `visual.analyze_image` | `marco/knowledge/ingest/documents.py`, `bench/chart_structure_benchmark.py`, `bench/chartqa_visual_benchmark.py`, `bench/hico_contact_benchmark.py` | no test calls it; `tests/test_document_kg.py::test_pptx_media_is_bound_to_its_slide_location` replaces it with a stub |
| `visual.VisualError` | `marco/knowledge/ingest/documents.py` | no test names it |
| `visual._merge_words` | tests only | `tests/test_document_visual.py::test_same_box_ocr_disagreement_uses_shorter_prefix` |
| `visual._chart_structure`, `_line_chart_structure`, `_pie_chart_structure` | tests only | `tests/test_document_visual.py` (`test_colored_bars_and_numeric_ticks_are_a_chart`, `test_multiple_thin_colored_series_and_ticks_are_a_line_chart`, `test_colored_circle_segments_and_number_are_a_pie_chart`) |
| `visual._table_structure` | tests only | `tests/test_document_visual.py::test_grid_lines_form_a_table_with_rows_and_columns` |
| `visual._hand_object_contacts` | tests only | `tests/test_document_visual.py::test_hand_object_contact_requires_a_confident_wrist_and_box_overlap` |
| `visual._spatial_relations` | tests only | `tests/test_document_visual.py::test_pairwise_spatial_relations_keep_direction_and_containment_separate` |
| `vlm.py`, `objects.py`, `pose.py` | run by path from `visual.py` (`VLM_SOURCE`, `OBJECT_SOURCE`, `POSE_SOURCE`) | no test names them |

The three `bench/` scripts above import `analyze_image` to measure chart type
detection and bar counts on ChartQA images and hand–object contact on HICO-DET
labels (their docstrings); their results are not reported here. The accuracy
of `analyze_image` on real documents: not measured.
