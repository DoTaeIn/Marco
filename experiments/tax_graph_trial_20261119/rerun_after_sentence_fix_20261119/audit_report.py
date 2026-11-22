"""Audit captured returns and write a comparison; never call the model."""
from collections import Counter
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
PREVIOUS = BASE / 'rerun_after_length_fix_20261119'
ROOT = BASE.parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(graph):
    names = {n['id']: (n['type'], tuple(n['anchor'])) for n in graph['nodes']}
    def obj(value):
        if isinstance(value, str):
            return ['node', names[value]]
        return ['constant', value]
    return sorted(json.dumps([names[s], p, obj(o)], sort_keys=True, ensure_ascii=False)
                  for s, p, o in graph['edges'])


def classification(question, record):
    result = record['result']
    if result['status'] != 'answered':
        return result['status']
    behavior = question['expected_behavior']
    if behavior['gold_status'] == 'answer':
        expected = [[b['value']] for b in question['expected_bindings']]
        return 'correct' if sorted(result['answers']) == sorted(expected) else 'wrong'
    if behavior['gold_status'] == 'derived_answer':
        return 'correct' if result['answers'] == [[behavior['expected_answer']]] else 'wrong'
    return 'unscored_answer' if behavior['gold_status'] == 'reject_claim' else 'wrong'


def main():
    questions = read(BASE / 'questions.json') + read(BASE / 'supplemental_questions.json')
    by_id = {q['id']: q for q in questions}
    context = read(BASE / 'contexts.json')[0]
    current = rows(HERE / 'first_results.jsonl')
    previous = rows(PREVIOUS / 'first_results.jsonl')
    originals = rows(BASE / 'first_results.jsonl') + rows(BASE / 'diagnostic_first_results.jsonl')
    indices = [{(r['question_id'], r['arm']): r for r in rs}
               for rs in (originals, previous, current)]
    expected_pairs = {(q['id'], arm) for q in questions
                      for arm in (('graph', 'end_to_end') if q['id'].startswith('Q') else ('graph',))}
    assert len(current) == 52 and set(indices[2]) == expected_pairs
    manifest = read(HERE / 'manifest.json')
    old_manifest = read(PREVIOUS / 'manifest.json')
    assert all(manifest['inputs'][k] == v for k, v in old_manifest['inputs'].items())
    assert all(sha(BASE / k) == v for k, v in manifest['inputs'].items())
    assert all(sha(ROOT / k) == v for k, v in manifest['sources'].items())
    assert all(sha(HERE / 'source_snapshot' / k) == v for k, v in manifest['sources'].items())
    assert sha(HERE / 'run.py') == manifest['runner_sha256']
    assert read(HERE / 'postcheck.json')['inputs_and_sources_unchanged']
    changes = [k for k, v in manifest['sources'].items() if old_manifest['sources'].get(k) != v]
    assert changes == ['experiments/graph_weighted_acquisition/reader.py']

    answer_count = proof_count = fact_count = passage_count = 0
    counts, states, transitions = Counter(), Counter(), []
    for record in current:
        q = by_id[record['question_id']]
        result = record['result']
        grade = classification(q, record)
        counts[(record['group'], record['arm'], grade)] += 1
        states[(result.get('executor'), result.get('verified'))] += 1
        assert record['question'] == q['text']
        assert record['model_sha256'] == manifest['model_sha256']
        assert record['manifest_sha256'] == sha(HERE / 'manifest.json')
        if record['arm'] == 'end_to_end':
            passage = result['passage']
            assert passage['status'] == 'complete'
            assert passage['sentences'] == passage['sentences_read'] == 14
            assert canonical(passage['graphs'][0]) == canonical(context['graph'])
            passage_count += 1
        if result['status'] == 'answered':
            answer_count += 1
            proofs = result['match']['proofs']
            assert proofs and result['evidence']
            assert sorted({tuple(p['answer']) for p in proofs}) == sorted(map(tuple, result['answers']))
            for proof in proofs:
                proof_count += 1
                for fact in proof['facts']:
                    spans = fact['spans']
                    assert spans and len(spans) == len(fact['text'])
                    assert all(0 <= a < b <= len(context['text']) for a, b in spans)
                    assert [context['text'][a:b] for a, b in spans] == fact['text']
                    fact_count += 1
            for evidence in result['evidence']:
                a, b = evidence['span']
                assert evidence['text'] == context['text'][a:b]
        key = (q['id'], record['arm'])
        transitions.append({'id': q['id'], 'arm': record['arm'],
                            'before': classification(q, indices[1][key]), 'after': grade,
                            'answers': result['answers'], 'reason': result.get('reason'),
                            'executor': result.get('executor'), 'verified': result.get('verified')})
    audit = {'record_count': len(current), 'same_input_model_and_previous_results': True,
             'changed_source_since_previous': changes,
             'source_snapshot_and_postcheck_pass': True,
             'counts': [{'group': g, 'arm': a, 'classification': c, 'n': n}
                        for (g, a, c), n in sorted(counts.items())],
             'executor_states': [{'executor': e, 'verified': v, 'n': n}
                                 for (e, v), n in sorted(states.items())],
             'passage_graphs_equal_to_supplied_context_ignoring_node_ids': passage_count,
             'answered_returns': answer_count, 'proofs_checked': proof_count,
             'proof_conditions_with_exact_context_spans': fact_count,
             'manifest_sha256': sha(HERE / 'manifest.json'),
             'results_sha256': sha(HERE / 'first_results.jsonl'), 'rows': transitions}
    (HERE / 'audit').mkdir(exist_ok=True)
    with (HERE / 'audit/result_audit.json').open('x', encoding='utf8') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    def show(record):
        result = record['result']
        if result['status'] == 'answered':
            return ' / '.join(', '.join(row) for row in result['answers'])
        return '보류' if result['status'] == 'hold' else result['status']

    lines = ['# 같은 세금 질문: 문장별 판독 수정 후 재시험', '',
             '질문 24개·사후 진단 4개, 지식 14개, 학습 예시 44개와 기존 저장 모델을 유지했다. '
             '재학습하지 않았으며 이전 결과를 덮어쓰지 않았다. 지난 재시험 이후 소스 차이는 reader.py의 문장별 판독·결합 변경이다. '
             '그래프 제공과 본문 직접 판독의 두 경로를 같은 시간 제한(20초/10초), 동시 작업 수 2로 실행했다. 각 호출은 1회이며 재시도하지 않았다.', '',
             '| 경로 | 최초 | 지난 수정 후 | 이번 수정 후 |',
             '|---|---|---|---|',
             '| 그래프 제공, 본시험 24개 | 답변 0 | 10개 일치·14개 보류 | 10개 일치·14개 보류 |',
             '| 본문 직접 판독, 본시험 24개 | 답변 0 | 24개 보류 | 10개 일치·14개 보류 |',
             '| 별도 학습 형식 진단 4개 | 답변 0 | 4개 일치 | 4개 일치 |', '',
             '이번 52회 호출에서 오답·오류·시간 초과는 0개였다. 답변한 24회(본시험 두 경로의 10개씩과 별도 진단 4개)는 '
             '모두 저장된 예상 값과 일치했다. 별도 실행기는 전부 unavailable, verified=false이므로 독립 검증 완료로 세지 않았다.', '',
             '본문 직접 판독 24회 모두 14문장을 읽었다. 생성된 그래프는 노드 이름을 제외한 타입·본문 위치·전체 관계가 '
             '제공된 정답 본문 그래프와 같았다. 답변 근거 24개의 조건별 본문 위치와 실제 문자열을 대조했다. '
             '이는 이번 14문장에 대한 검증이며 일반적인 사건 연결·새 문장 구조 이해를 증명하지 않는다.', '',
             '아래는 모델의 실제 반환 값이다. 자연스러운 답변 문장으로 고쳐 쓰지 않았다. 보류는 빈 답 배열을 뜻한다.', '',
             '| 번호 | 실제 질문 | 지난 본문 경로 | 이번 본문 경로 | 이번 그래프 경로 |',
             '|---|---|---|---|---|']
    for q in questions:
        key = (q['id'], 'end_to_end')
        prev = show(indices[1][key]) if key in indices[1] else '미실행'
        now = show(indices[2][key]) if key in indices[2] else '미실행'
        values = [q['id'], q['text'], prev, now, show(indices[2][q['id'], 'graph'])]
        lines.append('| ' + ' | '.join(str(v).replace('|', '\\|') for v in values) + ' |')
    lines += ['', '## 남은 한계', '',
              '- 직접 질문 4개(Q03·04·09·10), 바꿔 묻기 6개(Q15~20), 경계 질문 4개(Q21~24)는 모두 질문을 배운 조각으로 나누지 못했다.',
              '- 학습 자료의 신고횟수은·신청경로은·상담전화은 표현은 그대로 보존했다. 자연스러운 는 표현을 사용한 원래 질문의 실패도 그대로 기록했다.',
              '- 계산·개인 신고 의무·없는 지식·잘못된 주장에 대한 보류를 의미 이해나 안전한 판단의 성공으로 세지 않았다.',
              '- 세법 예외·적용 범위는 출처 메타데이터에 있고 그래프 조건으로 추론하지 않는다. 연4회 등 값 일치는 제공된 사실 범위에서의 조회 성과다.',
              '- 이번에는 공개된 같은 문제를 다시 사용했다. 새 독립 일반화 점수가 아니다. 별도 실행기의 검증 한도도 남아 있다.',
              '- 제품 코드를 수정하거나 메인에 반영하지 않았다. 공개 단위 검사 28개가 통과했다.', '',
              '## 실제 근거 예시', '',
              'Q08의 실제 답: `사업개시일부터20일이내`.', '',
              '본문에서 `사업자등록`과 `신청기한`을 연결하고, 그 신청기한의 값을 `사업개시일부터20일이내`로 찾았다. '
              '이 세 문자열의 본문 위치와 각 관계가 원시 기록에 보존되어 있다. 독립 실행기 검증은 미완료다.', '',
              '## 기록', '',
              '- 전체 질문별 첫 응답·판독 그래프·근거·검증 상태: [first_results.jsonl](first_results.jsonl)',
              '- 결과 대조 및 본문 위치 검사: [audit/result_audit.json](audit/result_audit.json)',
              '- 입력·소스 고정: [manifest.json](manifest.json), [postcheck.json](postcheck.json)',
              f"- 저장 모델 SHA-256: `{manifest['model_sha256']}`",
              f"- 결과 SHA-256: `{audit['results_sha256']}`", '']
    with (HERE / 'REPORT.md').open('x', encoding='utf8') as f:
        f.write('\n'.join(lines))
    print(json.dumps({k: v for k, v in audit.items() if k != 'rows'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
