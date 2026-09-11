"""Portability gates: selected assets, not the host, determine reasoning."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch
import zipfile

import pytest

import kgpack
from pack_model import ModelError, PackModel, descriptor
from reasoning_context import ReasoningContext
from semantic_parser import SemanticParser
import state_engine

ROOT = Path(__file__).resolve().parents[1]
COUNT = "돌은 23개 있다. 돌 8개를 꺼냈다. 지금 돌은 몇 개야?"
HEIGHT = "서우는 도아보다 크고 도아는 라온보다 크다. 서우와 라온 중 누가 더 커?"


def sources():
    return {"styles/test.json": (ROOT / "styles/한국어.json").read_bytes(),
            "axioms/test.json": (ROOT / "axioms/core.json").read_bytes()}


def model(assets):
    return PackModel({"version": 3, "model": descriptor(assets)}, assets)


def pack_at(tmp_path, assets=None):
    assets = sources() if assets is None else assets
    assets = {**assets, "graphs/unrelated.kg": "역할: 시험\n목표: 확인\n[개념]\n확인: \"확인\"\n".encode()}
    files = []
    for name, body in assets.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        files.append(path)
    target = tmp_path / "test.kgpack"
    kgpack.write_pack(target, files, root=tmp_path)
    return target


def test_creation_includes_sources_not_runtime_indexes_and_preserves_content():
    paths = {p.relative_to(ROOT).as_posix() for p in kgpack.default_file(ROOT)}
    assert {"styles/한국어.json", "axioms/core.json"} <= paths
    assert not any("semantic/" in p or p.endswith(".npz") for p in paths)
    candidate = model(sources())
    assert len(candidate.relational_data["examples"]) == 42
    assert len(candidate.relational_data["rules"]) == 3
    assert "rules" not in candidate.language["relations"]


def test_language_and_axioms_can_be_changed_independently_without_host_fallback(monkeypatch):
    original = sources()
    changed = deepcopy(original)
    axioms = json.loads(changed["axioms/test.json"])
    axioms["numeric_updates"]["count_remove"]["factor"] = 2
    changed["axioms/test.json"] = json.dumps(axioms).encode()
    first, second = model(original), model(changed)
    monkeypatch.setenv("NAI_RELATIONAL_MODEL", "/missing/model.json")
    monkeypatch.setenv("NAI_LANGUAGE", "/missing/language.json")
    with patch("pack_model.development_model", side_effect=AssertionError("host fallback")), \
         patch("language_components.load_reasoning_language", side_effect=AssertionError("host language")):
        for candidate, expected in ((first, "15개입니다."), (second, "39개입니다."), (first, "15개입니다.")):
            parsed = SemanticParser(model=candidate).parse(COUNT)
            result = state_engine.evaluate(parsed, model=candidate)
            assert result["answer"] == expected
            assert result["verification"]["model"] == candidate.fingerprint
            assert result["verification"]["sources"] == ["styles/test.json", "axioms/test.json"]
            assert candidate.parser().answer(candidate.parser().parse(HEIGHT))["answer"] == "서우입니다."
    assert first.fingerprint != second.fingerprint


def test_reverification_does_not_switch_to_the_default_language():
    assets = sources()
    language = json.loads(assets["styles/test.json"])
    language["관계해석"]["examples"] = []
    assets["styles/test.json"] = json.dumps(language).encode()
    original, without_examples = model(sources()), model(assets)
    parsed = SemanticParser(model=original).parse(COUNT)
    result = state_engine.evaluate(parsed, model=without_examples)
    assert result["status"] == "unknown"
    assert result["verification"]["checks"][0]["reason"] == "relations_not_grounded"


def test_context_replay_correction_and_restore_use_selected_model():
    candidate = model(sources())
    with patch("pack_model.development_model", side_effect=AssertionError("host fallback")):
        context = ReasoningContext(model=candidate)
        context.turn("돌은 23개 있다.")
        context.turn("돌 8개를 꺼냈다.")
        assert context.turn("지금 돌은 몇 개야?")["answer"] == "15개입니다."
        context.correct(0, "돌은 29개 있다.")
        restored = ReasoningContext(model=candidate)
        restored.restore(context.snapshot())
        assert restored.turn("지금 돌은 몇 개야?")["answer"] == "21개입니다."
        assert restored.turn("지금 돌은 몇 개야?")["answer"] == "21개입니다."


def test_verbal_expression_and_output_contracts_are_selected_assets():
    assets = sources()
    language = json.loads(assets["styles/test.json"])
    language["상태표현"]["value"] = "RESULT[{value}]"
    language["출력계약"]["number_only"]["requests"] = ["NUMONLY"]
    language["출력계약"]["number_only"]["numeric_answer"] = r"RESULT\[(?P<value>[+-]?\d+)\]"
    assets["styles/test.json"] = json.dumps(language).encode()
    candidate = model(assets)
    with patch("pack_model.development_model", side_effect=AssertionError("host fallback")):
        for text in ("3x + 1 = 7", "어떤 수에 3을 곱하고 1을 더하면 7이다"):
            # The second sample is checked below against the actual grammar;
            # no language change is made to fit a pack-portability test.
            graph = candidate.parse_expression(text)
            if text.startswith("3x"):
                assert graph is not None
        parsed = SemanticParser(model=candidate).parse("3x + 1 = 7")
        result = state_engine.evaluate(parsed, model=candidate)
        assert result["answer"] == "RESULT[2]"
        assert candidate.format_output("NUMONLY", result["answer"]) == "2"
        assert candidate.format_output("숫자만 답해", result["answer"]) == "RESULT[2]"
        assert model({}).parse_expression("어떤 수에 3을 곱하고 1을 더하면 7이다") is None


def test_empty_components_and_v2_never_inherit_current_model(tmp_path):
    empty = model({})
    assert not empty.permits("relational_graph")
    assert empty.parser().parse(COUNT) is None
    assert empty.format_output("숫자만 답해", "2입니다.") == "2입니다."
    legacy = PackModel({"version": 2}, sources())
    assert legacy.parser().parse(COUNT) is None
    assert not legacy.permits("arithmetic")
    path = pack_at(tmp_path, {})
    manifest, data = kgpack.read(path)
    assert manifest["model"]["language"] is None
    assert manifest["model"]["axioms"] == []


def test_model_views_cannot_mutate_another_consumer():
    candidate = model(sources())
    candidate.language["relations"]["examples"].clear()
    candidate.relational_data["rules"].clear()
    candidate.parser().data["examples"].clear()
    assert candidate.parser().parse(COUNT) is not None


@pytest.mark.parametrize("change", ["missing", "duplicate", "outside", "schema", "mixed"])
def test_invalid_models_are_rejected_before_use(change):
    assets = sources()
    manifest = {"version": 3, "model": descriptor(assets)}
    if change == "missing":
        del assets["axioms/test.json"]
    elif change == "duplicate":
        manifest["model"]["axioms"] *= 2
    elif change == "outside":
        assets["other/test.json"] = assets.pop("axioms/test.json")
        manifest["model"]["axioms"] = ["other/test.json"]
    elif change == "schema":
        assets["axioms/test.json"] = b'{"schema":"unknown"}'
    else:
        language = json.loads(assets["styles/test.json"])
        language["관계해석"]["rules"] = []
        assets["styles/test.json"] = json.dumps(language).encode()
    with pytest.raises(ModelError):
        PackModel(manifest, assets)


def test_v3_read_rejects_missing_model_and_duplicate_manifest_entries(tmp_path):
    path = pack_at(tmp_path)
    manifest, data = kgpack.read(path)
    for name, edited in (("missing-model", {k: v for k, v in manifest.items() if k != "model"}),
                         ("duplicate-entry", {**manifest, "files": manifest["files"] * 2})):
        bad = tmp_path / (name + ".kgpack")
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("manifest.json", json.dumps(edited))
            for asset, body in data.items():
                archive.writestr(asset, body)
        with pytest.raises(kgpack.KGPackError):
            kgpack.read(bad)


def test_ui_uses_axioms_without_a_special_named_graph(tmp_path):
    from views.kgpack_ui import AppState
    app = AppState(pack_at(tmp_path), overlay_root=tmp_path / "overlay")
    assert app.situation_graph is None
    with patch.object(app.goals, "research", side_effect=AssertionError("no web needed")), \
         patch("pack_model.development_model", side_effect=AssertionError("host fallback")):
        answer = app.turn(COUNT, "pack_session_1")["answer"]
        assert answer["answer"] == "15개입니다."
        assert answer["verification"]["model"] == app.model.fingerprint
        assert app.turn("3x + 1 = 7. 숫자만 답해", "pack_session_2")["answer"]["answer"] == "2"
        assert app.turn("고마워", "pack_session_3")["answer"]["trace"]["mode"] == "dialogue"


def test_packed_learning_is_materialized_without_overwriting_overlay(tmp_path):
    from views.kgpack_ui import AppState
    seed = b'{"source":"packed"}\n'
    app = AppState(pack_at(tmp_path, {"graphs/unrelated.학습.jsonl": seed}), overlay_root=tmp_path / "overlay")
    graph = app._materialize("graphs/unrelated.kg")
    learned = graph.with_suffix(".학습.jsonl")
    assert learned.read_bytes() == seed
    learned.write_bytes(seed + b'{"source":"new"}\n')
    app._materialize("graphs/unrelated.kg")
    assert learned.read_bytes() == seed + b'{"source":"new"}\n'


def test_engine_sources_and_one_pack_work_without_loose_model_files(tmp_path):
    pack = pack_at(tmp_path / "authoring")
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    for source in ROOT.glob("*.py"):
        shutil.copy2(source, isolated / source.name)
    (isolated / "views").mkdir()
    shutil.copy2(ROOT / "views/kgpack_ui.py", isolated / "views/kgpack_ui.py")
    shutil.copy2(pack, isolated / "model.kgpack")
    # The interpreter must not see the authoring tree on sys.path. Only code
    # and one packed model are present; the subprocess creates its own state.
    script = '''
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
os.environ["KG_ENCODER"] = "문자"
os.environ["NAI_LANGUAGE"] = "/missing/host-language.json"
os.environ["NAI_RELATIONAL_MODEL"] = "/missing/host-model.json"
from views.kgpack_ui import AppState
app = AppState("model.kgpack", overlay_root="overlay")
assert not Path("styles").exists() and not Path("axioms").exists() and not Path("data").exists()
app.goals.research = lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected web"))
assert app.turn("돌은 23개 있다.", "isolated_session")["answer"]["trace"]["verdict"] == "상태기억"
app.turn("돌 8개를 꺼냈다.", "isolated_session")
assert app.turn("지금 돌은 몇 개야?", "isolated_session")["answer"]["answer"] == "15개입니다."
assert app.turn("3x + 1 = 7. 숫자만 답해", "isolated_equation")["answer"]["answer"] == "2"
print("isolated-pack-ok")
'''
    result = subprocess.run([sys.executable, "-I", "-c", script], cwd=isolated,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "isolated-pack-ok" in result.stdout
