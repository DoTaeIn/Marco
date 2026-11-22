"""Score already captured public tax returns; do not invoke inference."""
from collections import Counter
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
CONFIGS = ('frozen44', 'variants44', 'expanded132')


def read(p):
    return json.loads(p.read_text(encoding='utf8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def canonical(graph):
    nodes = {n['id']: [n['type'], n['anchor']] for n in graph['nodes']}
    return sorted(json.dumps([nodes[s], p, ['node', nodes[o]] if isinstance(o, str) else ['constant', o]],
                             sort_keys=True, ensure_ascii=False) for s, p, o in graph['edges'])


def grade(q, r):
    if r['status'] != 'answered':
        return r['status']
    behavior = q['expected_behavior']['gold_status']
    expected = [[b['value']] for b in q.get('expected_bindings', [])]
    if behavior == 'answer':
        ok = sorted(r['answers']) == sorted(expected) and not r.get('claim')
    elif behavior == 'reject_claim':
        claim = r.get('claim')
        ok = bool(claim and claim['claimed'] == '0%' and claim['holds'] is False
                  and sorted(r['answers']) == sorted(expected))
    elif behavior == 'derived_answer':
        ok = r['answers'] == [[q['expected_behavior']['expected_answer']]]
    else:
        ok = False
    return 'correct_value_partial' if ok and r.get('partial') else 'correct_value' if ok else 'wrong'


def main():
    questions = read(BASE / 'questions.json') + read(BASE / 'supplemental_questions.json')
    by_id = {q['id']: q for q in questions}
    context = read(BASE / 'contexts.json')[0]
    records = [json.loads(s) for s in (HERE / 'first_results.jsonl').read_text().splitlines()]
    index = {(r['config'], r['question_id'], r['arm']): r for r in records}
    expected = {(c, q['id'], a) for c in CONFIGS for q in questions
                for a in (('graph', 'end_to_end') if q['id'].startswith('Q') else ('graph',))}
    assert len(records) == len(index) == 156 and set(index) == expected
    manifest = read(HERE / 'manifest.json')
    assert read(HERE / 'postcheck.json')['inputs_models_and_sources_unchanged']
    assert all(sha(ROOT / p) == h for p, h in manifest['inputs'].items())
    assert all(sha(ROOT / p) == h and sha(HERE / 'source_snapshot' / p) == h
               for p, h in manifest['sources'].items())
    assert all(sha(HERE / 'models' / (c + '.json')) == h for c, h in manifest['models'].items())
    assert sha(HERE / 'run.py') == manifest['runner_sha256']
    assert manifest['models']['frozen44'] == sha(BASE / 'model.json')
    counts, verification, transitions = Counter(), Counter(), []
    graph_equal, proofs_checked, conditions_checked = Counter(), 0, 0
    previous_records = [json.loads(s) for s in
                        (BASE / 'rerun_after_sentence_fix_20261119/first_results.jsonl').read_text().splitlines()]
    previous = {(r['question_id'], r['arm']): r for r in previous_records}
    for row in records:
        q, r = by_id[row['question_id']], row['result']
        assert row['question'] == q['text'] and row['context_text'] == context['text']
        assert row['model_sha256'] == manifest['models'][row['config']]
        assert row['manifest_sha256'] == sha(HERE / 'manifest.json')
        verdict = grade(q, r)
        counts[row['config'], row['group'], row['arm'], verdict] += 1
        verification[row['config'], r.get('executor'), bool(r.get('verified'))] += 1
        if row['arm'] == 'end_to_end':
            p = r.get('passage') or {}
            same = p.get('status') == 'complete' and canonical(p['graphs'][0]) == canonical(context['graph'])
            graph_equal[row['config'], bool(same)] += 1
        if r['status'] == 'answered':
            assert r['match']['proofs'] and r['evidence']
            assert sorted({tuple(p['answer']) for p in r['match']['proofs']}) == sorted(map(tuple, r['answers']))
            for proof in r['match']['proofs']:
                proofs_checked += 1
                for fact in proof['facts']:
                    assert fact['spans'] and len(fact['spans']) == len(fact['text'])
                    assert all(0 <= a < b <= len(context['text']) for a, b in fact['spans'])
                    assert [context['text'][a:b] for a, b in fact['spans']] == fact['text']
                    conditions_checked += 1
            for evidence in r['evidence']:
                a, b = evidence['span']
                assert evidence['text'] == context['text'][a:b]
        before = previous[q['id'], row['arm']]['result']
        transitions.append({'config': row['config'], 'id': q['id'], 'arm': row['arm'],
                            'before': grade(q, before), 'after': verdict, 'answers': r['answers'],
                            'partial': r.get('partial', []), 'claim': r.get('claim'),
                            'reason': r.get('reason'), 'executor': r.get('executor'),
                            'verified': r.get('verified'), 'proposals': r.get('proposals', [])})
    prior_sources = read(BASE / 'rerun_after_sentence_fix_20261119/manifest.json')['sources']
    changed = [p for p, h in manifest['sources'].items() if prior_sources.get(p) != h]
    audit = {'records': 156, 'unique_calls': 156, 'source_input_model_postcheck': True,
             'original_context_and_questions_in_all_configs': True,
             'counts': [{'config': c, 'group': g, 'arm': a, 'verdict': v, 'n': n}
                        for (c, g, a, v), n in sorted(counts.items())],
             'verification': [{'config': c, 'executor': e, 'verified': v, 'n': n}
                              for (c, e, v), n in sorted(verification.items())],
             'passage_graph_comparison': [{'config': c, 'same_graph': s, 'n': n}
                                          for (c, s), n in sorted(graph_equal.items())],
             'proofs_checked': proofs_checked, 'proof_conditions_checked': conditions_checked,
             'changed_sources_since_previous': changed, 'models': manifest['models'],
             'results_sha256': sha(HERE / 'first_results.jsonl'), 'transitions': transitions}
    (HERE / 'audit').mkdir(exist_ok=True)
    with (HERE / 'audit/result_audit.json').open('x', encoding='utf8') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    def shown(row):
        r = row['result']
        if r['status'] != 'answered':
            return '보류' if r['status'] == 'hold' else r['status']
        s = ' / '.join(', '.join(values) for values in r['answers'])
        if r.get('claim'):
            s += ' (주장 ' + r['claim']['claimed'] + ': ' + str(r['claim']['holds']) + ')'
        if r.get('partial'):
            s += ' [부분 해석]'
        return s

    lines = ['# 같은 세금 문제: 학습·판독 수정 후 재시험', '',
             '원래 질문 24개와 별도 진단 4개를 그대로 사용했다. 모든 조건에 원래의 14개 사실, 같은 본문 바이트를 제공했다. '
             '조사를 고친 별도 본문은 사용하지 않았다. 각 조건에서 그래프 제공/본문 직접 판독 경로를 실행했다(본시험 48회+진단 4회). '
             '3개 조건 합계 156회이며 각 호출의 첫 결과를 보존하고 재시도하지 않았다.', '',
             '| 조건 | 모델과 자료 | 본문 경로 24개 |', '|---|---|---|',
             '| 지난 시험 | 기존 44예시 저장 모델 | 10개 값 일치·14개 보류 |',
             '| frozen44 | 저장 모델 바이트 그대로 + 현재 코드 | 10개 값 일치·14개 보류 |',
             '| variants44 | 같은 44예시로 재구축 + 기존 원문 조사 변형 자료 | 14개 값 일치·10개 보류 |',
             '| expanded132 | 저장된 확장 132예시로 구축, 조사 변형 자료는 별도 주입하지 않음 | 18개 값 일치·6개 보류 |', '',
             '각 조건의 그래프 제공 경로도 본문 경로와 같은 값·주장 판정을 냈다. 별도 진단 4개는 세 조건 모두 4개 값 일치다. '
             '본시험 점수에 이 4개를 합치지 않았다. 전체 156회에서 잘못된 반환 값·오류·시간 초과는 0개다.', '',
             'expanded132의 18개 중 15개는 질문 일부를 무시했다는 표시가 없고, 3개(Q16·Q20·Q24)는 부분 해석이다. '
             '전부 독립 검증 미완료다. Q24는 10%를 반환하면서 0%라는 주장에는 false를 기록했다. '
             '값 일치와 전체 질문 이해, 독립 검증은 서로 다른 항목으로 집계했다.', '',
             '## 전체 질문과 실제 출력', '',
             '아래는 본문 경로의 원시 반환 값이다. 완성된 답변 문장으로 고쳐 쓰지 않았다. 그래프 경로도 값과 주장 판정이 같다.', '',
             '| 번호 | 실제 질문 | 기존 모델+현재 코드 | 조사 변형 적용 | 확장 132예시 |',
             '|---|---|---|---|---|']
    for q in questions:
        arm = 'end_to_end' if q['id'].startswith('Q') else 'graph'
        vals = [q['id'], q['text']] + [shown(index[c, q['id'], arm]) for c in CONFIGS]
        lines.append('| ' + ' | '.join(str(v).replace('|', '\\|') for v in vals) + ' |')
    lines += ['', '진단 C01~C04는 그래프 경로만 실행했다. 원래 있던 신고횟수은 등의 문법 오류도 수정하지 않았다.', '',
              '## 부분 해석과 남은 실패', '']
    for row in records:
        if row['config'] != 'expanded132' or row['arm'] != 'end_to_end':
            continue
        r = row['result']
        if r.get('partial'):
            lines.append('- ' + row['question_id'] + ': ' + '; '.join(r['partial']))
        elif r['status'] != 'answered':
            lines.append('- ' + row['question_id'] + ': ' + r.get('reason', r['status']))
    lines += ['', '## 해석상의 한계', '',
              '- 132개 예시의 추가 질문 표현은 이전 실패 질문을 보고 사람이 작성했다. 이번 18/24는 같은 문제에서의 개선이며 독립적인 새 표현 일반화 성과가 아니다.',
              '- variants44는 같은 예시로 모델을 재구축하고 기존 조사 변형 자료를 넣은 조건이다. 기존 모델 그대로인 조건과 별도로 표시했다.',
              '- 사용자에게 단어 뜻을 확인받아 저장하는 대화 학습은 이 문제에서 사용되지 않았다. 어떤 확인도 주입하지 않았고 해당 기능의 개선 효과를 주장하지 않는다.',
              '- Q22의 보류는 질문을 읽지 못한 결과이고, Q23은 읽은 질문에 맞는 지식이 없어서 보류했다. 보류 두 건을 이해 성공 두 건으로 세지 않았다.',
              '- 세법 적용 예외는 출처 메타데이터이고 모든 예외를 그래프로 추론한 결과가 아니다. 출처·날짜·범위는 원시 기록과 원래 facts.json에 보존했다.',
              '- graph 경로도 현재 공개 answer_graph API를 사용했다. 과거 수제 wrapper가 지원하지 않던 주장 판정·부분 해석 표시를 현재 제품 경로로 검사하기 위한 변경이며 실행기에 기록했다.',
              '- 메인·런타임 본체는 변경하지 않았다. 제품 소스에 수정하지 않고 실험 기록만 새 폴더에 저장했다. 공개 검사 39개 통과.', '',
              '## 감사', '',
              f'- 본문 그래프 비교: {dict(graph_equal)} (노드 이름을 제외하고 타입·앵커·전체 관계 비교).',
              f'- 반환 근거 {proofs_checked}개, 조건 {conditions_checked}개의 본문 위치와 문자열 일치를 확인했다.',
              '- 모든 입력·이전 결과·모델·소스의 실행 전후 해시가 같았다.',
              '- [전체 첫 결과와 근거](first_results.jsonl) · [결과 감사](audit/result_audit.json) · [고정 명세](manifest.json)',
              f"- 결과 SHA-256: `{audit['results_sha256']}`", '']
    with (HERE / 'REPORT.md').open('x', encoding='utf8') as f:
        f.write('\n'.join(lines))
    print(json.dumps({k: v for k, v in audit.items() if k != 'transitions'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
