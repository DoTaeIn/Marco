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
import encoder
from pack_model import ModelError, PackModel, descriptor
from reasoning_context import ReasoningContext
from semantic_parser import SemanticParser
import state_engine

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

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
    # Possession state syntax, two independently declared operation lexemes,
    # the elided-location event shape, and state-lookup action syntax are pack
    # data, not runtime indexes.
    # Promise creation/cancellation/status are pack-declared state examples.
    assert len(candidate.relational_data["examples"]) == 101   # round 5: two holding forms (G5.3 batch 1)
    assert len(candidate.relational_data["rules"]) == 6
    assert "rules" not in candidate.language["relations"]


def test_two_packs_keep_their_encoder_vectors_and_ui_routes_separate(tmp_path):
    """인코더는 import 시 한 번 고르는 전역 설정이 아니라 팩의 실행 자산이다."""
    from views.kgpack_ui import AppState

    def configured_assets(dimensions):
        language = json.loads((ROOT / "styles/한국어.json").read_text(encoding="utf-8"))
        language["인코더"] = {"mode": "문자", "dimensions": dimensions,
                          "jamo_weight": 0.5, "smoothing": 0,
                          "route_threshold": 0.43, "cluster_threshold": 0.30,
                          "goal_similarity_threshold": 0.62, "device": "cpu"}
        return {"styles/test.json": json.dumps(language, ensure_ascii=False).encode(),
                "axioms/core.json": (ROOT / "axioms/core.json").read_bytes(),
                "graphs/graph_일상추론.kg": (ROOT / "graphs/graph_일상추론.kg").read_bytes()}

    first = AppState(pack_at(tmp_path / "first", configured_assets(256)),
                     overlay_root=tmp_path / "first-overlay")
    second = AppState(pack_at(tmp_path / "second", configured_assets(512)),
                      overlay_root=tmp_path / "second-overlay")
    graph = "graphs/graph_일상추론.kg"
    first.select(graph)
    second.select(graph)
    first_vector = next(iter(first.graph["vec"].values()))
    second_vector = next(iter(second.graph["vec"].values()))
    assert first_vector.shape[1] == 256
    assert second_vector.shape[1] == 512

    # 두 번째 팩을 실행한 뒤에도 첫 번째 팩의 선택과 벡터 차원은 그대로다.
    first.ask("민수 구슬은 몇 개야?")
    assert next(iter(first.graph["vec"].values())).shape[1] == 256
    with first.model.encoder.activate():
        assert encoder._embed("확인").shape == (256,)
    with second.model.encoder.activate():
        assert encoder._embed("확인").shape == (512,)


def test_encoder_declaration_rejects_unbounded_or_unknown_pack_settings():
    assets = sources()
    language = json.loads(assets["styles/test.json"])
    language["인코더"] = {"mode": "문자", "dimensions": 32, "unexpected": True}
    assets["styles/test.json"] = json.dumps(language, ensure_ascii=False).encode()
    with pytest.raises(ValueError):
        model(assets)


def test_default_pack_keeps_collected_facts_and_definition_evidence(tmp_path):
    graph = tmp_path / "graphs" / "daily.kg"
    collected = tmp_path / "graphs" / "daily.수집.jsonl"
    definition = tmp_path / "data" / "위키" / "정의문.jsonl"
    graph.parent.mkdir(); definition.parent.mkdir(parents=True)
    graph.write_text("역할: 시험\n목표: 확인\n[개념]\n확인: \"확인\"\n", encoding="utf-8")
    collected.write_text('{"주제":"시험"}\n', encoding="utf-8")
    definition.write_text('{"말":"시험어", "정의":"팩 안 정의다."}\n', encoding="utf-8")
    paths = {path.relative_to(tmp_path).as_posix() for path in kgpack.default_file(tmp_path)}
    assert {"graphs/daily.kg", "graphs/daily.수집.jsonl", "data/위키/정의문.jsonl"} <= paths


def test_ui_definition_uses_the_packed_asset_not_the_host(tmp_path):
    from views.kgpack_ui import AppState
    assets = sources()
    assets["data/위키/정의문.jsonl"] = (
        '{"말":"팩시험", "정의":"이 문장은 팩에 든 정의 근거다."}\n'.encode())
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed definition must answer locally")):
        result = app.turn("팩시험 요약해줘", "packed_definition")
    assert "팩에 든 정의 근거" in result["answer"]["answer"]
    assert app.definitions.source == app.overlay / "data/위키/정의문.jsonl"


def test_ui_composes_packed_collected_evidence_and_plan_steps(tmp_path):
    from views.kgpack_ui import AppState
    assets = sources()
    assets["graphs/unrelated.수집.jsonl"] = (
        '{"주제":"해양 산성화","주제별칭":["해양 산성화"],"출처":"a.example",'
        '"URL":"https://a.example/a","문장들":["해양 산성화는 대기 이산화탄소가 바닷물에 녹을 때 진행된다."]}\n'
        '{"주제":"해양 산성화","주제별칭":["해양 산성화"],"출처":"b.example",'
        '"URL":"https://b.example/b","문장들":["해양 산성화를 줄이려면 이산화탄소 배출을 줄이는 일이 필요하다."]}\n'
    ).encode()
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed evidence must answer locally")):
        summary = app.turn("해양 산성화 요약해줘", "packed_collection")
        plan = app.turn("해양 산성화 계획해줘", "packed_collection")
    assert [row["source"] for row in summary["answer"]["composition"]["selected"]] == [
        "https://a.example/a", "https://b.example/b"]
    assert plan["answer"]["answer"] == "1. 해양 산성화를 줄이려면 이산화탄소 배출을 줄이는 일이 필요하다."


def test_ui_does_not_let_one_long_source_hide_an_independent_packed_source(tmp_path):
    from views.kgpack_ui import AppState
    assets = sources()
    first = {"주제": "광합성", "주제별칭": ["광합성"], "출처": "a.example",
             "URL": "https://a.example/a", "문장들": ["첫 출처 문장 %d." % number for number in range(9)]}
    second = {"주제": "광합성", "주제별칭": ["광합성"], "출처": "b.example",
              "URL": "https://b.example/b", "문장들": ["둘째 출처의 독립 문장이다."]}
    assets["graphs/unrelated.수집.jsonl"] = (
        json.dumps(first, ensure_ascii=False) + "\n" + json.dumps(second, ensure_ascii=False) + "\n").encode()
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed evidence must answer locally")):
        result = app.turn("광합성 요약해줘", "source_diversity")
    selected = result["answer"]["composition"]["selected"]
    assert [row["source"] for row in selected[:2]] == ["https://a.example/a", "https://b.example/b"]


def test_ui_uses_declared_cause_and_step_dependencies_from_the_pack(tmp_path):
    from views.kgpack_ui import AppState
    assets = sources()
    record = {"주제": "해양 산성화", "주제별칭": ["해양 산성화"],
              "출처": "a.example", "URL": "https://a.example/a", "claims": [
                  {"id": "effect", "text": "바닷물의 산성도가 높아진다.", "relation": "effect",
                   "depends_on": ["cause"]},
                  {"id": "cause", "text": "이산화탄소가 바닷물에 녹기 때문이다.", "relation": "cause"},
                  {"id": "measure", "text": "배출량을 측정한다.", "actionable": True},
                  {"id": "reduce", "text": "배출을 줄인다.", "actionable": True,
                   "depends_on": ["measure"]},
              ]}
    assets["graphs/unrelated.수집.jsonl"] = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed evidence must answer locally")):
        explained = app.turn("해양 산성화 설명해줘", "structured_collection")
        planned = app.turn("해양 산성화 계획해줘", "structured_collection")
    assert explained["answer"]["composition"]["mode"] == "grounded_causal_explanation"
    assert explained["answer"]["composition"]["selected"] == [
        {"text": "이산화탄소가 바닷물에 녹기 때문이다.", "source": "https://a.example/a"},
        {"text": "바닷물의 산성도가 높아진다.", "source": "https://a.example/a"},
    ]
    assert planned["answer"]["composition"]["mode"] == "grounded_dependency_plan"
    assert planned["answer"]["answer"] == "1. 배출량을 측정한다.\n2. 배출을 줄인다."


def test_ui_plan_checks_the_current_conversation_state_before_using_a_declared_goal(tmp_path):
    """계획의 상태 전제는 팩 문구가 아니라 이 대화에서 확인한 사실이어야 한다."""
    from views.kgpack_ui import AppState
    assets = sources()
    record = {"주제": "해양 산성화", "주제별칭": ["해양 산성화"],
              "출처": "a.example", "URL": "https://a.example/a", "claims": [
                  {"id": "measure", "text": "배출량을 측정한다.", "actionable": True},
                  {"id": "reduce", "text": "배출을 줄인다.", "actionable": True,
                   "depends_on": ["measure"], "achieves": ["해양 산성화 완화"],
                   "requires_state": [["배출량", "count", "10"]]},
              ]}
    assets["graphs/unrelated.수집.jsonl"] = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed evidence must answer locally")):
        # 팩에 목표 행동이 있어도, 아직 상태가 없으면 계획으로 확정하지 않는다.
        absent = app.turn("해양 산성화 계획해줘", "stateful_plan")
        observed = app.turn("배출량은 10개 있다.", "stateful_plan")
        present = app.turn("해양 산성화 계획해줘", "stateful_plan")
    assert absent["phase"] != "answer" or "composition" not in absent.get("answer", {})
    assert observed["answer"]["trace"]["verdict"] == "상태기억"
    assert present["answer"]["answer"] == "1. 배출량을 측정한다.\n2. 배출을 줄인다."


def test_ui_plan_uses_declared_action_effects_from_packed_evidence(tmp_path):
    """팩에 든 결과 상태가 실제 대화의 다음 행동 전제로 전달된다."""
    from views.kgpack_ui import AppState
    assets = sources()
    record = {"주제": "공책", "주제별칭": ["공책"], "출처": "a.example", "URL": "https://a.example/a", "claims": [
        {"id": "shelve", "text": "공책을 책장으로 옮긴다.", "actionable": True,
         "effects": [["공책", "location", "책장"]]},
        {"id": "label", "text": "책장에 둔 공책에 분류표를 붙인다.", "actionable": True,
         "achieves": ["공책 정리"], "requires_state": [["공책", "location", "책장"]]},
    ]}
    assets["graphs/unrelated.수집.jsonl"] = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed evidence must answer locally")):
        app.turn("공책은 서랍에 있었다.", "effect_plan")
        planned = app.turn("공책 정리 계획해줘", "effect_plan")
    assert planned["answer"]["answer"] == "1. 공책을 책장으로 옮긴다.\n2. 책장에 둔 공책에 분류표를 붙인다."


def test_ui_compares_two_packed_topics_without_inventing_a_difference(tmp_path):
    from views.kgpack_ui import AppState
    assets = sources()
    assets["graphs/unrelated.수집.jsonl"] = (
        '{"주제":"해양 산성화","주제별칭":["해양 산성화"],"출처":"a.example",'
        '"URL":"https://a.example/a","문장들":["해양 산성화는 바닷물의 성질을 바꾼다."]}\n'
        '{"주제":"지구 온난화","주제별칭":["지구 온난화"],"출처":"b.example",'
        '"URL":"https://b.example/b","문장들":["지구 온난화는 지구 평균 기온의 장기 상승을 뜻한다."]}\n'
    ).encode()
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed evidence must answer locally")):
        result = app.turn("해양 산성화와 지구 온난화 비교해줘", "packed_compare")
    answer = result["answer"]
    assert answer["trace"]["verdict"] == "원문근거비교"
    assert "바닷물의 성질" in answer["answer"] and "평균 기온" in answer["answer"]
    assert "더" not in answer["answer"]


def test_ui_compares_only_the_shared_structured_attribute(tmp_path):
    from views.kgpack_ui import AppState
    assets = sources()
    records = [
        {"주제": "해양 산성화", "주제별칭": ["해양 산성화"], "출처": "a.example",
         "URL": "https://a.example/a", "claims": [
             {"text": "해양 산성화 원문", "attributes": {"영향 대상": "바다", "원인": "탄소"}}]},
        {"주제": "지구 온난화", "주제별칭": ["지구 온난화"], "출처": "b.example",
         "URL": "https://b.example/b", "claims": [
             {"text": "지구 온난화 원문", "attributes": {"영향 대상": "대기", "원인": "탄소"}}]},
    ]
    assets["graphs/unrelated.수집.jsonl"] = (
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)).encode()
    app = AppState(pack_at(tmp_path, assets), overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed evidence must answer locally")):
        result = app.turn("해양 산성화와 지구 온난화 비교해줘", "structured_compare")
    composed = result["answer"]["composition"]
    assert composed["mode"] == "grounded_attribute_comparison"
    assert composed["answer"] == "**영향 대상**\n- 해양 산성화: 바다\n- 지구 온난화: 대기"


def test_exported_pack_carries_approved_collection_to_a_fresh_runtime(tmp_path):
    from views.kgpack_ui import AppState
    source = tmp_path / "source.kgpack"
    kgpack.write_pack(source, [ROOT / "graphs/graph_자가학습.kg"] + kgpack.model_files(ROOT), root=ROOT)
    app = AppState(source, overlay_root=tmp_path / "overlay")
    graph = app._materialize("graphs/graph_자가학습.kg")
    collection = Path(str(graph)[:-3] + ".수집.jsonl")
    collection.write_text(
        '{"주제":"해양 산성화","주제별칭":["해양 산성화"],"출처":"a.example",'
        '"URL":"https://a.example/a","문장들":["해양 산성화는 바닷물의 성질을 바꾼다."]}\n'
        '{"주제":"해양 산성화","주제별칭":["해양 산성화"],"출처":"b.example",'
        '"URL":"https://b.example/b","문장들":["해양 산성화는 이산화탄소 증가와 관련 있다."]}\n'
        '{"주제":"해양 산성화","주제별칭":["해양 산성화"],"출처":"c.example",'
        '"URL":"https://c.example/c","claims":[{"id":"cause","text":"이산화탄소가 바닷물에 녹기 때문이다.","relation":"cause"},'
        '{"id":"effect","text":"바닷물의 산성도가 높아진다.","relation":"effect","depends_on":["cause"]}]}\n',
        encoding="utf-8")
    exported = tmp_path / "learned.kgpack"
    report = app.export_pack(exported)
    assert "graphs/graph_자가학습.수집.jsonl" in report["files"]
    _manifest, assets = kgpack.read(exported)
    assert "graphs/graph_자가학습.수집.jsonl" in assets
    fresh = AppState(exported, overlay_root=tmp_path / "fresh-overlay")
    with patch.object(fresh.goals, "research", side_effect=AssertionError("exported evidence must answer locally")):
        result = fresh.turn("해양 산성화 요약해줘", "exported_collection")
        explained = fresh.turn("해양 산성화 설명해줘", "exported_collection")
    assert "바닷물의 성질" in result["answer"]["answer"]
    assert explained["answer"]["composition"]["mode"] == "grounded_causal_explanation"
    assert explained["answer"]["composition"]["selected"] == [
        {"text": "이산화탄소가 바닷물에 녹기 때문이다.", "source": "https://c.example/c"},
        {"text": "바닷물의 산성도가 높아진다.", "source": "https://c.example/c"}]


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


def test_validated_relational_learning_moves_with_the_pack(tmp_path):
    """표현 교정은 호스트 모델이 아니라 팩의 선택 자산에서 복원된다."""
    from relational_semantics import RelationalParser
    from views.kgpack_ui import AppState
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    learned = model_dir / "relational.json"
    parser = RelationalParser()
    assert parser.learn({"text": "하루는 모래에 비해 키가 크다",
                         "slots": {"a": "하루", "b": "모래"},
                         "meaning": {"triple": ["$a", "taller", "$b"]}})
    parser.save(learned)
    graph = tmp_path / "graphs" / "daily.kg"
    graph.parent.mkdir()
    graph.write_text(Path("graphs/graph_일상추론.kg").read_text(encoding="utf-8"), encoding="utf-8")
    style = tmp_path / "styles" / "한국어.json"
    axiom = tmp_path / "axioms" / "core.json"
    style.parent.mkdir(); axiom.parent.mkdir()
    style.write_bytes(Path("styles/한국어.json").read_bytes())
    axiom.write_bytes(Path("axioms/core.json").read_bytes())
    pack = tmp_path / "learned.kgpack"
    kgpack.write_pack(pack, [graph, learned, style, axiom], root=tmp_path)
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("packed learning must answer locally")):
        result = app.turn("서우는 도아에 비해 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?", "packed_learning")
    assert result["answer"]["answer"] == "서우입니다."
    assert any(row["path"] == "models/relational.json" for row in result["answer"]["verification"]["model_assets"])
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    for source in ROOT.glob("*.py"):
        shutil.copy2(source, isolated / source.name)
    (isolated / "views").mkdir()
    shutil.copy2(ROOT / "views/kgpack_ui.py", isolated / "views/kgpack_ui.py")
    # The runtime now includes the marco package (the language seam).
    shutil.copytree(ROOT / "marco", isolated / "marco",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(pack, isolated / "learned.kgpack")
    script = '''
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
os.environ["KG_ENCODER"] = "문자"
os.environ["NAI_RELATIONAL_MODEL"] = "/missing/host-model.json"
from views.kgpack_ui import AppState
assert not Path("styles").exists() and not Path("axioms").exists() and not Path("models").exists()
app = AppState("learned.kgpack", overlay_root="overlay")
app.goals.research = lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected web"))
result = app.turn("서우는 도아에 비해 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?", "isolated_learned")
assert result["answer"]["answer"] == "서우입니다."
assert any(x["path"] == "models/relational.json" for x in result["answer"]["verification"]["model_assets"])
print("isolated-learned-pack-ok")
'''
    completed = subprocess.run([sys.executable, "-I", "-c", script], cwd=isolated,
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "isolated-learned-pack-ok" in completed.stdout


@pytest.mark.parametrize("change, error", [
    ("declaration", "relational_model_changes_pack_declaration"),
    ("replacement", "relational_model_not_an_extension"),
])
def test_packed_relational_learning_cannot_replace_its_declared_base(tmp_path, change, error):
    """학습 자산은 표현 확장이지 언어팩·기본 사례의 대체물이 아니다."""
    from relational_semantics import RelationalParser
    assets = sources()
    learned = RelationalParser(data=model(assets).relational_data,
                               language_pack=model(assets).language).data
    if change == "declaration":
        learned["answer_suffix"] = "변조"
    else:
        learned["examples"] = learned["examples"][1:]
    assets["models/relational.json"] = json.dumps(learned, ensure_ascii=False).encode()
    manifest = {"version": 3, "model": descriptor(assets)}
    with pytest.raises(ModelError, match=error):
        PackModel(manifest, assets)


def test_engine_sources_and_one_pack_work_without_loose_model_files(tmp_path):
    pack = pack_at(tmp_path / "authoring")
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    for source in ROOT.glob("*.py"):
        shutil.copy2(source, isolated / source.name)
    (isolated / "views").mkdir()
    shutil.copy2(ROOT / "views/kgpack_ui.py", isolated / "views/kgpack_ui.py")
    # The runtime now includes the marco package (the language seam).
    shutil.copytree(ROOT / "marco", isolated / "marco",
                    ignore=shutil.ignore_patterns("__pycache__"))
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


def test_pack_reports_line_ending_diagnostics_without_weakening_byte_identity(tmp_path):
    crlf = kgpack.content_identity(b"alpha\r\nbeta\r\n")
    lf = kgpack.content_identity(b"alpha\nbeta\n")
    assert crlf["sha256"] != lf["sha256"]
    assert crlf["lf_normalized_sha256"] == lf["lf_normalized_sha256"]
    assert crlf["line_endings"] == {"crlf": 2, "lf": 0, "cr": 0}

    manifest, _assets = kgpack.read(pack_at(tmp_path))
    assert all("lf_normalized_sha256" in row and "line_endings" in row
               for row in manifest["files"])
