import numpy as np
import pytest

import engine


def graph(phrases):
    g = {"공통층": {"node": phrases}, "사례층": {}, "무관층": {}}
    g["vec"] = {"node": np.array([engine._embed_sub(engine.mask_numbers(p)) for p in engine.expand_examples(g, phrases)])}
    return g


@pytest.mark.parametrize("question,phrases", [
    ("중요한 단계가 끝나는 시점", ["프로젝트 진행 과정에서 주요 단계가 끝나는 시점", "일정의 중요한 이정표"]),
    ("서로 독립적인 작업", ["동시에 독립적인 작업을 수행한다"]),
])
def test_node_and_sparse_scores_match_same_alias_geometric_mean(question, phrases):
    g = graph(phrases)
    q, qi = engine._embed(question), engine._embed_sub(question)
    reverse = engine._reverse_examples(g, "node")
    forward = g["vec"]["node"] @ q
    expected = float(np.sqrt(np.maximum(forward, 0) * np.maximum(reverse @ qi, 0)).max())
    assert engine.match(question, ["node"], g)[1] == round(expected, 3)
    slot = engine.sparse_vec(g["vec"], flip_table={"node": reverse})["node"]
    assert slot[5][0].dtype == np.int8
    assert engine._sparse_score(slot, q, inner_vec=qi) == pytest.approx(expected, abs=1e-6)


def test_reverse_cache_is_compact_and_refreshes_after_alias_replacement():
    g = graph(["독립 작업의 완료 시간"])
    old = engine._reverse_examples(g, "node")
    assert old.dtype == np.int8
    assert old.nbytes == g["vec"]["node"].nbytes // 4
    new = graph(["다른 작업의 시작 시점"])
    g["공통층"], g["vec"] = new["공통층"], new["vec"]
    assert engine._reverse_examples(g, "node") is not old


def test_sparse_score_handles_empty_final_rows_and_negative_overlap():
    matrix = np.array([[1., 0., 0., 0., 0., 0.], [0., 0., 0., 0., 0., 0.]], dtype=np.float32)
    slot = engine.sparse_vec({"n": matrix}, flip_table={"n": matrix})["n"]
    assert engine._sparse_score(slot, -matrix[0], inner_vec=-matrix[0]) == 0
    assert engine._sparse_score(slot, matrix[0], inner_vec=matrix[0]) == 1


def test_geometric_score_survives_kgbin_roundtrip(tmp_path):
    import kgbin
    phrase = "서로 독립적인 작업의 완료 시간"
    g = graph([phrase])
    reverse = engine._reverse_examples(g, "node")
    slots = engine.sparse_vec(g["vec"], {"node": np.array([len(phrase)], dtype=np.float32)}, {"node": reverse})
    path = tmp_path / "score.kgbin"
    kgbin.write_pack(slots, path, value_fmt="float32")
    restored, _ = kgbin.unpack(path)
    q, qi = engine._embed("독립 작업"), engine._embed_sub("독립 작업")
    assert engine._sparse_score(restored["node"], q, inner_vec=qi) == pytest.approx(
        engine._sparse_score(slots["node"], q, inner_vec=qi), abs=1e-6)


def test_explicit_evidence_precedes_goal_gate_but_generic_question_does_not():
    g = engine.load("graphs/graph_순위_추월.kg")
    question = ("당신은 마라톤 대회에서 달리고 있습니다. 결승점을 코앞에 두고 "
                "전력 질주하여 2등인 사람을 추월했습니다. 지금 당신은 몇 등일까요?")
    session = engine.Session(g)
    assert "2등" in session.reply(question)
    assert session.result() == "성립"
    assert engine.judge(g, "지금 몇 시야")[0] in ("미지", "B2")


def test_declared_acronym_lookup_survives_long_explanation():
    text = "QXZ는 주소를 찾는 가상의 프로토콜이며 연결 전에 이름을 확인한다"
    g = graph([text])
    index = {"공통층": {"example.kg": [text]}, "vec": {"example.kg": g["vec"]["node"]}}
    assert engine.pick_graph("what is QXZ", index)[0] == "example.kg"
    assert engine.pick_graph("what is QXY", index)[0] is None
