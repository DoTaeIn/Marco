"""Public controls for opposing proposition support across events."""
import pytest
from experiments.graph_language_repair.core import read_text


def conflicts(text):
    doc = read_text(text)
    return doc, [c for c in doc['contradictions'] if c['kind'] == 'polarity_across_events']


@pytest.mark.parametrize('text', [
    '루빈이 명세서를 대조했다. 나린이 명세서를 대조하지 않았다.',
    '루빈이 명세서를 대조했다. 루빈이 도면을 대조하지 않았다.',
    '루빈이 명세서를 대조했다. 루빈이 명세서를 확인하지 않았다.',
])
def test_different_filled_propositions_are_not_opposing(text):
    _, found = conflicts(text)
    assert not found


def test_same_proposition_retains_both_sides_support():
    doc, found = conflicts('루빈이 명세서를 대조했다. 루빈이 명세서를 대조하지 않았다.')
    assert len(found) == 1
    conflict = found[0]
    rows = [row for row in doc['rows'] if row['id'] in conflict['rows']]
    assert set(conflict['subjects']) == {row['triple'][0] for row in rows}
    for subject in conflict['subjects']:
        assert {'action', 'polarity', 'actor', 'object'} <= {
            row['triple'][1] for row in rows if row['triple'][0] == subject}
    assert conflict['policy'] == 'contradiction:opposing_propositions'


def test_distinct_explicit_time_roles_block_that_reading_pair():
    doc, found = conflicts('어제 루빈이 명세서를 대조했다. 오늘 루빈이 명세서를 대조하지 않았다.')
    times = {row['event']: row['value'] for row in doc['roles'] if row['role'] == 'time'}
    assert len(set(times.values())) == 2
    assert all(not (all(event in times for event in c['subjects'])
                    and len({times[event] for event in c['subjects']}) > 1)
               for c in found)
