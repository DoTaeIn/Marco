"""Public controls for compositional adjunct and literal span competition."""
import pytest
from experiments.graph_language_repair.core import read_text
from experiments.graph_language_repair import public_api as api


def values(doc, role):
    return {item['value'] for item in doc['roles'] if item['role'] == role}


@pytest.mark.parametrize('prefix', ['지난주', '이번달', '다음해', '저번주말', '12월', '３시'])
def test_composed_time_and_literal_compete(prefix):
    doc = read_text(prefix + ' 기록 담당자가 도면을 색인했다.')
    assert {prefix + ' 기록 담당자', '기록 담당자'} <= values(doc, 'actor')
    assert prefix in values(doc, 'time')
    assert all(reading['competes_with'] for reading in doc['readings'])


def test_quoted_time_named_entity_and_unrelated_title_stay_whole():
    quoted = read_text("'지난주 기록 담당자'가 도면을 색인했다.")
    assert values(quoted, 'actor') == {'지난주 기록 담당자'}
    assert not values(quoted, 'time')
    plain = read_text('마을 방송 담당자가 도면을 색인했다.')
    assert values(plain, 'actor') == {'마을 방송 담당자'}


def test_negation_and_multisentence_keep_scope_and_competition():
    doc = read_text('라온이 문서를 확인했다. 이번달 택배 기사가 도면을 색인하지 않았다.')
    assert {'이번달 택배 기사', '택배 기사'} <= values(doc, 'actor')
    assert any(event['polarity'] is False for event in doc['events'])


def test_question_does_not_assert_corrupted_actor():
    result = api.answer(api.read('지난주 미린이 도면을 색인했다.'), '누가 도면을 색인했어?')
    assert result['status'] != 'answered'


def test_passive_and_adnominal_keep_literal_rivals():
    passive = read_text('지난주 도면이 미린에게 색인되었다.')
    assert {'지난주 도면', '도면'} <= values(passive, 'object')
    assert all(event['voice'] == 'passive' for event in passive['events'])
    adnominal = read_text('지난주 기록한 담당자가 도면을 색인했다.')
    assert {'지난주 기록한 담당자', '기록한 담당자'} <= values(adnominal, 'actor')
