"""Public controls for opaque nominal references and event ambiguity."""
from experiments.graph_language_repair.core import read_text


def verification(text):
    return [h for h in read_text(text)["hypotheses"] if h["kind"] == "verification"]


def test_composed_nominal_and_grounded_entity_rival():
    result = verification('보고서에 따르면 미린이 도면을 색인했다. 감사팀이 그 색인을 사실로 확인했다.')
    assert [h['status'] for h in result] == ['accepted']
    assert result[0]['independent_result'] == 'confirmed'
    assert any(e['kind'] == 'composed_nominal_reference' for e in result[0]['evidence'])
    rival = verification('미린이 색인을 보관했다. 나린이 도면을 색인했다. 감사팀이 그 색인을 사실로 확인했다.')
    assert rival and all(h['status'] == 'candidate' for h in rival)
    multiple = verification('미린이 도면을 색인했다. 나린이 지도를 색인했다. 감사팀이 그 색인을 사실로 확인했다.')
    assert len(multiple) == 2 and all(h['status'] == 'candidate' for h in multiple)
    known = verification('미린이 도면을 전달했다. 감사팀이 그 전달을 사실로 확인했다.')
    assert any(h['status'] == 'accepted' for h in known)


def test_generic_happening_head_requires_unique_target_and_no_entity_rival():
    one = verification('보고서에 따르면 미린이 도면을 색인했다. 감사팀이 그 일을 사실로 확인했다.')
    assert [h['status'] for h in one] == ['accepted']
    assert one[0]['independent_result'] == 'confirmed'
    multiple = verification('미린이 도면을 색인했다. 나린이 지도를 보관했다. 감사팀이 그 일을 사실로 확인했다.')
    assert len(multiple) == 2 and all(h['status'] == 'candidate' for h in multiple)
    rival = verification('미린이 작업을 색인했다. 감사팀이 그 작업을 사실로 확인했다.')
    assert rival and all(h['status'] == 'candidate' for h in rival)


def test_conjunctive_do_form_preserves_both_opaque_predicates():
    doc = read_text('미린이 도면을 색인하고 보관했다.')
    assert [e['predicate_analysis'].get('lemma') for e in doc['events']] == ['색인', '보관']
    assert all(e['semantic_status'] == 'unknown' for e in doc['events'])
