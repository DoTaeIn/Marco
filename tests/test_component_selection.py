# -*- coding: utf-8 -*-
"""부품 선택은 **한 곳에서** 한다 — 팩 선언.

환경변수로 고르면 한 실행 안에서 팩마다 다르게 고를 수 없고, 팩을 둘 띄우면
나중에 켠 쪽이 앞엣것의 선택을 덮는다. 이 파일이 지키는 것은 그 격리다.
"""
import json
from pathlib import Path

import pytest

import marco.language.passage_components as passage_components
from pack_model import PackModel, ModelError, descriptor

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

ROOT = Path(__file__).resolve().parents[1]


def _model(component=None):
    language = json.loads((ROOT / "styles/한국어.json").read_text(encoding="utf-8"))
    if component is not None:
        language["부품"] = {passage_components.KIND: component}
    assets = {"styles/x.json": json.dumps(language, ensure_ascii=False).encode(),
              "axioms/core.json": (ROOT / "axioms/core.json").read_bytes()}
    return PackModel({"version": 3, "model": descriptor(assets)}, assets)


def test_two_packs_choose_different_components_without_touching_each_other():
    chosen = _model("marco.language.passages:LabelLearnedClassifier")
    plain = _model()
    sentence = "실험 결과 정확도가 12% 올랐다."

    first = passage_components.resolve_backend(model=chosen).classify(sentence)
    assert passage_components.resolve_backend(model=plain).classify(sentence) == ["진술"]
    # 다른 팩을 띄운 뒤에도 앞엣것의 선택이 그대로다.
    assert passage_components.resolve_backend(model=chosen).classify(sentence) == first
    assert first != ["진술"]
    assert (passage_components.resolve_backend(model=chosen)
            is not passage_components.resolve_backend(model=plain))


def test_a_component_is_loaded_only_when_it_is_chosen():
    plain = _model()
    assert plain.component(passage_components.KIND) is None
    # 안 고른 부품은 불러오지 않는다. 고르지 않았는데 기본 부품을 이 자리에서
    # 정하면, 부르는 쪽이 제 기본값을 쓸 수가 없다.
    assert isinstance(passage_components.resolve_backend(model=plain),
                      passage_components.StatementFallback)


def test_an_injected_component_outranks_the_declaration():
    class Fixed:
        def classify(self, _text):
            return ["코드"]

    chosen = _model("marco.language.passages:LabelLearnedClassifier")
    assert passage_components.resolve_backend(Fixed(), model=chosen).classify("무엇") == ["코드"]


def test_a_malformed_declaration_is_refused_when_the_pack_is_read():
    language = json.loads((ROOT / "styles/한국어.json").read_text(encoding="utf-8"))
    language["부품"] = {passage_components.KIND: "모듈만적음"}
    assets = {"styles/x.json": json.dumps(language, ensure_ascii=False).encode(),
              "axioms/core.json": (ROOT / "axioms/core.json").read_bytes()}
    with pytest.raises((ValueError, ModelError)):
        PackModel({"version": 3, "model": descriptor(assets)}, assets)


def test_a_backend_without_classify_is_refused():
    with pytest.raises(TypeError):
        passage_components.resolve_backend(object())
