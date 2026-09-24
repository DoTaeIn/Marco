"""tools/doc_facts.py: the numbers README.md cites, and the checks behind the docs index.

These tests read recorded reports and the checkout's files; none runs an exam or
the engine. The frozen-report files never change, so their numbers are pinned.
"""
import contextlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import doc_facts  # noqa: E402


def _rows(title_prefix, run="after-w3"):
    for title, _source, rows in doc_facts.frozen_facts(run):
        if title.startswith(title_prefix):
            return dict(rows)
    raise AssertionError(title_prefix)


def test_frozen_after_w3_numbers_match_the_reports():
    dialogue = _rows("dialogue gate")
    assert dialogue["gate 2: answerable turns correct"].startswith("21 / 108 (19.4%)")
    assert dialogue["gate 3: confident answers without evidence"] == 0
    assert dialogue["gate 3: uses of retracted evidence"] == 0
    assert dialogue["statements recorded"].startswith("82 / 150")
    composition = _rows("composition gate")
    assert composition["gate 5: replies composed from a meaning"].startswith("340 / 340 (100.0%); passed through 0")
    reasoning = _rows("reasoning gate")
    assert reasoning["questions correct among parsed"].startswith("148 / 151 (98.0%); wrong 0")
    assert reasoning["gate 6: problems correct among parsed"].startswith("108 / 111 (97.3%)")


def test_gate_summary_after_w3():
    summary = {n: met for n, met, _ in doc_facts.gate_summary("after-w3")}
    assert summary == {2: False, 3: True, 5: True, 6: True}


def test_older_runs_read_with_the_same_code():
    assert _rows("dialogue gate", "round3")["gate 2: answerable turns correct"].startswith("21 / 108")
    assert _rows("composition gate", "after-w2")["gate 5: replies composed from a meaning"].startswith("339 / 340")
    missing = [rows for _t, _s, rows in doc_facts.frozen_facts("no-such-run")[:3]]
    assert missing == [None, None, None]


def test_frozen_prints_no_sentence_from_any_exam():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert doc_facts.cmd_frozen("after-w3") == 0
    printed = out.getvalue()
    said = set()
    for _kind, pattern in doc_facts.FROZEN_REPORTS:
        with open(os.path.join(ROOT, pattern.format(run="after-w3")), encoding="utf-8") as f:
            report = json.load(f)
        for row in report["rows"]:
            value = row.get("say")
            if isinstance(value, str) and len(value.strip()) >= 6:
                said.add(value.strip())
    assert len(said) > 100
    leaked = sum(1 for sentence in said if sentence in printed)     # a count, so a failure prints no sentence
    assert leaked == 0


def test_layout_partitions_the_root():
    facts = doc_facts.layout_facts()
    moved = [name for name, _target in facts["move"]]
    assert sorted(facts["stay"] + moved) == facts["root"]
    assert "conftest" in facts["stay"] or "conftest" not in facts["root"]
    assert all(len(names) > 1 for names in facts["shared_targets"].values())
    for target in facts["taken_targets"]:
        assert os.path.isfile(os.path.join(ROOT, *target.split(".")) + ".py")


def _tree(tmp_path, index_text, files):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text(index_text, encoding="utf-8")
    for rel in files:
        path = docs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return str(tmp_path)


def test_index_names_unlinked_documents_and_broken_links(tmp_path):
    root = _tree(tmp_path, "[a](a.md) [b](ko/%EB%B9%84.md) [gone](gone.md) [web](https://example.org/x.md)",
                 ["a.md", "ko/비.md", "ko/c.json", ".DS_Store"])
    unlisted, broken = doc_facts.index_facts(root)
    assert unlisted == [os.path.join("docs", "ko", "c.json")]
    assert broken == [os.path.join("docs", "gone.md")]


def test_doc_problem_checks_heading_order(tmp_path):
    arch = tmp_path / "docs" / "architecture"
    arch.mkdir(parents=True)
    headings = list(doc_facts.HEADINGS)
    (arch / "good.md").write_text("\n".join(["# good"] + headings) + "\n", encoding="utf-8")
    (arch / "bad.md").write_text("\n".join(["# bad"] + headings[1:] + headings[:1]) + "\n", encoding="utf-8")
    assert doc_facts.doc_problem("good", str(tmp_path)) is None
    assert "out of order" in doc_facts.doc_problem("bad", str(tmp_path))
    assert doc_facts.doc_problem("absent", str(tmp_path)).startswith("no file")
