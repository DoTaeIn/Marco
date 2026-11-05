"""Optional local graph-native dialogue demo. No network, language model or learning."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from marco.runtime.ground_language_work import advance_ground_language


def source(identity, text):
    return {'id': identity, 'text': text, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description='그래프 기반 문장 해석·질문·증명 예제 (자가학습 꺼짐)')
    parser.add_argument('--case', type=Path, default=ROOT/'examples/graph_native/ko-understanding.json')
    parser.add_argument('--ask', action='store_true', help='초기 사실 없이 필요한 정보를 되묻기')
    parser.add_argument('--non-interactive', action='store_true')
    parser.add_argument('--proof', action='store_true')
    args = parser.parse_args()
    data = json.loads(args.case.read_text(encoding='utf-8'))
    program = json.loads((ROOT/'programs/foundation-ground-language.json').read_text())
    information = json.loads((ROOT/'programs/hypothesis-leaf-question-step.json').read_text())
    statements = [] if args.ask else [dict(source=source('demo:statement:'+str(i), text), caller_attested=True)
                                     for i, text in enumerate(data['statements'])]
    query = source('demo:query', data['query'])
    positional = (program, data['model'], information, data['rules'], statements, query, data['context_id'])
    result = advance_ground_language(*positional)
    turns = 0
    while result['status'] == 'asking' and not args.non_interactive and turns < 2:
        print('MARCO:', result['text'])
        print('등록된 전체 문장으로 답변하세요. 빈 입력은 종료합니다.')
        try:
            text = input('답변> ')
        except EOFError:
            break
        if not text:
            break
        turns += 1
        result = advance_ground_language(*positional, session=result['session'],
                    reply={'source': source('demo:reply:'+str(turns), text), 'caller_attested': True})
    print(json.dumps({'status': result['status'], 'answer': result.get('text'),
                      'reason': result.get('reason'), 'self_learning': False}, ensure_ascii=False, indent=2))
    if args.proof:
        print(json.dumps((result.get('information_work') or {}).get('goal_record'), ensure_ascii=False, indent=2))
    return 0 if result['status'] in ('asking', 'confirmed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
