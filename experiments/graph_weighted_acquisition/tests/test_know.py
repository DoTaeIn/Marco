"""Public development checks for the first structured-input stage (know.py).

The ferry line is made up. These are development examples written by the implementer; they
are not an independent evaluation and say nothing about reading natural language.
"""
import copy
import json
import random
from pathlib import Path

from experiments.graph_weighted_acquisition import know as K

PACKS = Path(__file__).resolve().parents[1] / 'packs'
WORDS = json.loads((PACKS / 'ferry_words.json').read_text(encoding='utf8'))
FACTS = json.loads((PACKS / 'ferry_facts.json').read_text(encoding='utf8'))
SOURCE = {'doc': 'made-up example'}


def q(where, find=(), names=None, ask='value', **more):
    return dict({'schema': K.QUESTION, 'find': list(find), 'where': where, 'names': names or {}, 'ask': ask}, **more)


CAPACITY = q([['?ship', '정원', '?v']], ['?v'], {'?ship': '모래섬호'})
FROM_EAST = q([['?ship', '출발항', '?port']], ['?ship'], {'?port': '동쪽항'})
PHONE = q([['?ship', '출발항', '?port'], ['?port', '문의전화', '?v']], ['?v'], {'?ship': '모래섬호'})


def facts_plus(*statements, **more):
    return dict(FACTS, statements=FACTS['statements'] + list(statements), **more)


def values(result):
    return [a['values'] for a in result['answers']]


def test_direct_lookup_keeps_the_unit_and_cites_the_statement():      # D1
    r = K.answer(WORDS, FACTS, CAPACITY)
    assert r['status'] == 'answered' and r['inferred'] == 'answered'
    assert values(r) == [[{'n': '120', 'unit': '명'}]] and r['answers'][0]['proofs'] == [['K01']]
    assert r['verification'] == {'steps': 'agrees', 'completeness': 'agrees', 'cause': []}


def test_another_name_is_resolved_and_reported():                      # D2
    r = K.answer(WORDS, FACTS, dict(CAPACITY, names={'?ship': '1호선'}))
    assert r['status'] == 'answered' and values(r) == [[{'n': '120', 'unit': '명'}]]
    assert r['notes'] == ['"1호선" is another name for "모래섬호"']


def test_two_relations_are_joined_and_both_steps_are_cited():          # D3
    r = K.answer(WORDS, FACTS, PHONE)
    assert r['status'] == 'answered' and values(r) == [[{'text': '0412'}]]
    assert r['answers'][0]['proofs'] == [['K02', 'K06']]


def test_every_answer_is_given():                                      # D4
    r = K.answer(WORDS, FACTS, FROM_EAST)
    assert r['status'] == 'answered'
    assert sorted(v[0]['name'] for v in values(r)) == ['모래섬호', '바람개비호']


def test_stated_false_is_false_and_not_stated_is_unknown():            # D8, D9
    no = K.answer(WORDS, FACTS, q([['?ship', '자전거적재', True]], names={'?ship': '모래섬호'}, ask='check'))
    assert no['status'] == 'answered' and no['claim'] == {'holds': False, 'steps': ['K03']}
    turned = K.answer(WORDS, FACTS, q([['?ship', '자전거적재', False]], names={'?ship': '모래섬호'}, ask='check'))
    assert turned['claim'] == {'holds': True, 'steps': ['K03']}
    unknown = K.answer(WORDS, FACTS, q([['?ship', '자전거적재', True]], names={'?ship': '바람개비호'}, ask='check'))
    assert unknown['status'] == 'no_knowledge' and unknown['claim'] is None


def test_a_claimed_value_is_checked_against_the_single_stated_value():
    wrong = K.answer(WORDS, FACTS, q([['?ship', '정원', {'n': '100', 'unit': '명'}]], names={'?ship': '모래섬호'}, ask='check'))
    assert wrong['status'] == 'answered' and wrong['claim'] == {'holds': False, 'steps': ['K01']}
    right = K.answer(WORDS, FACTS, q([['?ship', '정원', {'n': '120', 'unit': '명'}]], names={'?ship': '모래섬호'}, ask='check'))
    assert right['claim'] == {'holds': True, 'steps': ['K01']}


def test_a_relation_declared_complete_makes_absence_false_and_says_so():
    words = copy.deepcopy(WORDS)
    next(r for r in words['relations'] if r['p'] == '자전거적재')['absent_means'] = 'false'
    r = K.answer(words, FACTS, q([['?ship', '자전거적재', True]], names={'?ship': '바람개비호'}, ask='check'))
    assert r['status'] == 'answered' and r['claim'] == {'holds': False, 'steps': []} and r['assumptions']


def test_a_name_shared_by_two_things_is_asked_about_not_guessed():     # D14
    r = K.answer(WORDS, FACTS, dict(CAPACITY, names={'?ship': '등대호'}))
    assert r['status'] == 'ambiguous_entity' and r['answers'] == []
    assert sorted(c['name'] for c in r['candidates']) == ['작은등대호', '큰등대호']
    assert r['verification']['completeness'] == 'agrees'       # agreement does not turn it into an answer


def test_known_relation_without_a_fact_and_unknown_name_are_no_knowledge():   # D16 (가)
    assert K.answer(WORDS, FACTS, q([['?ship', '선령', '?v']], ['?v'], {'?ship': '모래섬호'}))['status'] == 'no_knowledge'
    assert K.answer(WORDS, FACTS, dict(CAPACITY, names={'?ship': '없는배'}))['status'] == 'no_knowledge'


def test_units_are_converted_before_values_are_compared():
    words = dict(WORDS, units=WORDS['units'] + [{'unit': '쌍', 'base': '명', 'per_base': '1/2'}])
    r = K.answer(words, FACTS, q([['?ship', '정원', {'n': '60', 'unit': '쌍'}]], ['?ship']))
    assert r['status'] == 'answered' and [v[0]['name'] for v in values(r)] == ['모래섬호']


# ---- the check rejects damaged results, and a rejection is not "could not check"

def judged(question, result, words=WORDS, facts=FACTS):
    return K.final(result, K.check(words, facts, question, result))


def test_a_wrong_step_is_rejected():                                   # D22
    r = K.ask(K.load(WORDS, FACTS), CAPACITY)
    r['answers'][0]['proofs'] = [['K06']]
    out = judged(CAPACITY, r)
    assert out['status'] == 'verification_failed' and out['verification']['steps'] == 'rejects'
    assert out['answers'] == [] and out['withheld']['answers'] and 'K06' in out['reason']


def test_a_left_out_answer_is_rejected_although_the_rest_is_right():   # D25
    r = K.ask(K.load(WORDS, FACTS), FROM_EAST)
    r['answers'] = [a for a in r['answers'] if a['values'][0]['name'] != '바람개비호']
    out = judged(FROM_EAST, r)
    assert out['status'] == 'verification_failed'
    assert out['verification'] == {'steps': 'agrees', 'completeness': 'rejects',
                                   'cause': ["missing answer: (('thing', 't.wind'),)"]}


def test_an_added_answer_without_ground_is_rejected():
    r = K.ask(K.load(WORDS, FACTS), FROM_EAST)
    r['answers'].append({'values': [{'thing': 't.big', 'name': '큰등대호'}], 'proofs': [['K02']]})
    out = judged(FROM_EAST, r)
    assert out['status'] == 'verification_failed'
    assert out['verification']['steps'] == 'rejects' and out['verification']['completeness'] == 'rejects'


def test_saying_nothing_is_known_when_something_is_gets_rejected():
    r = K._result('no_knowledge', 'damaged on purpose')
    out = judged(CAPACITY, r)
    assert out['status'] == 'verification_failed' and out['inferred'] == 'no_knowledge'


def test_answering_for_one_of_two_things_with_the_same_name_is_rejected():
    question = dict(CAPACITY, names={'?ship': '등대호'})
    r = K._result('answered', 'damaged on purpose', answers=[{'values': [{'n': '200', 'unit': '명'}], 'proofs': [['K16']]}])
    assert judged(question, r)['status'] == 'verification_failed'


def test_a_wrong_claim_verdict_is_rejected():
    question = q([['?ship', '자전거적재', True]], names={'?ship': '모래섬호'}, ask='check')
    r = K.ask(K.load(WORDS, FACTS), question)
    r['claim'] = {'holds': True, 'steps': ['K03']}
    assert judged(question, r)['status'] == 'verification_failed'


def test_a_check_that_cannot_run_gives_unverified_never_a_rejection_or_an_answer():
    words = dict(WORDS, limits={'enumeration': 1})
    ok = K.answer(words, FACTS, FROM_EAST)
    assert ok['status'] == 'unverified' and ok['inferred'] == 'answered'
    assert ok['verification']['completeness'] == 'not_checked' and len(ok['answers']) == 2
    nothing = K.answer(words, FACTS, q([['?ship', '출발항', '?port'], ['?ship', '문의전화', '?v']], ['?v']))
    assert nothing['status'] == 'unverified' and nothing['inferred'] == 'no_knowledge'


def test_search_bound_gives_limit_exceeded_not_a_partial_answer():
    r = K.answer(dict(WORDS, limits={'search_steps': 1}), FACTS, FROM_EAST)
    assert r['status'] == 'limit_exceeded' and r['answers'] == [] and r['verification'] is None


# ---- knowledge this stage cannot use is refused, not used

def test_a_statement_said_both_ways_blocks_the_answer():
    facts = facts_plus({'id': 'X1', 's': 't.sand', 'p': '자전거적재', 'holds': True, 'source': SOURCE})
    r = K.answer(WORDS, facts, q([['?ship', '자전거적재', True]], names={'?ship': '모래섬호'}, ask='check'))
    assert r['status'] == 'conflict' and r['claim'] is None
    assert r['conflicts'] == [{'subject': 't.sand', 'relation': '자전거적재', 'statements': ['K03', 'X1']}]


def test_two_values_for_a_single_valued_relation_block_the_answer_only_where_they_matter():   # D10, D24
    facts = facts_plus({'id': 'K12', 's': 't.wind', 'p': '정원', 'o': {'n': '80', 'unit': '명'}, 'source': SOURCE},
                       {'id': 'K13', 's': 't.wind', 'p': '정원', 'o': {'n': '90', 'unit': '명'}, 'source': SOURCE})
    r = K.answer(WORDS, facts, dict(CAPACITY, names={'?ship': '바람개비호'}))
    assert r['status'] == 'conflict' and r['answers'] == [] and r['conflicts'][0]['statements'] == ['K12', 'K13']
    assert K.answer(WORDS, facts, CAPACITY)['status'] == 'answered'
    # A question over every ship's capacity reads the conflicting pair too.
    assert K.answer(WORDS, facts, q([['?ship', '정원', '?v']], ['?ship', '?v']))['status'] == 'conflict'


def test_a_qualified_statement_is_never_used_as_an_unqualified_fact():
    for field, value in (('where', {'요일구분': '평일'}), ('valid', ['2026-01-01', None]), ('supersedes', 'K01')):
        facts = facts_plus({'id': 'K04', 's': 't.sand', 'p': '선령', 'o': {'n': '7', 'unit': '년'}, 'source': SOURCE, field: value})
        k = K.load(WORDS, facts)
        assert k['unusable'] == [{'kind': 'statement', 'id': 'K04', 'reason': 'not supported yet: ' + field}]
        r = K.answer(WORDS, facts, q([['?ship', '선령', '?v']], ['?v'], {'?ship': '모래섬호'}))
        assert r['status'] == 'out_of_scope' and r['answers'] == [] and r['blocked'][0]['id'] == 'K04'
        assert K.answer(WORDS, facts, CAPACITY)['status'] == 'answered'


def test_rules_and_changes_are_refused_and_block_what_they_could_alter():
    rule = {'id': 'R1', 'if': [['?s', '출발항', '?p']], 'then': ['?s', '정원', {'n': '1', 'unit': '명'}], 'source': SOURCE}
    with_rule = dict(FACTS, rules=[rule])
    assert K.answer(WORDS, with_rule, CAPACITY)['status'] == 'out_of_scope'
    assert K.answer(WORDS, with_rule, FROM_EAST)['status'] == 'answered'
    with_change = dict(FACTS, changes=[{'recorded': 9, 'retracts': 'K02', 'source': SOURCE}])
    assert K.answer(WORDS, with_change, FROM_EAST)['status'] == 'out_of_scope'      # K02 must not be used as if it stood
    assert K.answer(WORDS, with_change, CAPACITY)['status'] == 'answered'
    unknown_target = dict(FACTS, changes=[{'recorded': 9, 'retracts': 'nowhere', 'source': SOURCE}])
    assert K.answer(WORDS, unknown_target, CAPACITY)['status'] == 'out_of_scope'


def test_question_features_of_later_stages_are_out_of_scope():
    for more in ({'at': '2026-12-01'}, {'known_at': 3}, {'given': [['_p', '정원', {'n': '1', 'unit': '명'}]]}, {'ask': 'count'}):
        assert K.answer(WORDS, FACTS, dict(CAPACITY, **more))['status'] == 'out_of_scope'
    assert K.answer(WORDS, FACTS, q([['?ship', '자전거적재', False]], ['?ship']))['status'] == 'out_of_scope'


def test_bad_records_are_listed_with_a_reason_and_every_record_is_accounted_for():
    bad = [{'id': 'B1', 's': 't.sand', 'p': '선령', 'o': {'n': '7', 'unit': '년'}},                       # no source
           {'id': 'B2', 's': 't.sand', 'p': '색깔', 'o': {'text': '흰색'}, 'source': SOURCE},              # unknown relation
           {'id': 'B3', 's': 't.sand', 'p': '선령', 'o': {'n': '7', 'unit': '달'}, 'source': SOURCE},      # undeclared unit
           {'id': 'B4', 's': 't.none', 'p': '선령', 'o': {'n': '7', 'unit': '년'}, 'source': SOURCE},      # unknown subject
           {'id': 'K01', 's': 't.wind', 'p': '선령', 'o': {'n': '7', 'unit': '년'}, 'source': SOURCE},     # repeated id
           {'id': 'B6', 's': 't.sand', 'p': '선령', 'o': {'text': '칠년'}, 'source': SOURCE}]              # wrong kind of value
    k = K.load(WORDS, facts_plus(*bad))
    assert [u['id'] for u in k['unusable']] == ['B1', 'B2', 'B3', 'B4', 'K01', 'B6'] and all(u['reason'] for u in k['unusable'])
    assert k['counts'] == {'given': 13, 'loaded': 7, 'unusable': 6}
    r = K.answer(WORDS, facts_plus(*bad), CAPACITY)
    assert r['status'] == 'answered' and r['counts']['unusable'] == 6


def test_the_order_of_records_does_not_change_any_result():           # D20, in part
    questions = [CAPACITY, FROM_EAST, PHONE, dict(CAPACITY, names={'?ship': '등대호'}),
                 q([['?ship', '자전거적재', True]], names={'?ship': '모래섬호'}, ask='check')]
    first = [K.answer(WORDS, FACTS, x) for x in questions]
    for seed in range(5):
        rng = random.Random(seed)
        words, facts = copy.deepcopy(WORDS), copy.deepcopy(FACTS)
        for part in (words['things'], words['relations'], facts['statements']):
            rng.shuffle(part)
        assert [K.answer(words, facts, x) for x in questions] == first
