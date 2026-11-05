"""Explicit experimental composition demo; no language model or self-learning."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from marco.runtime.ground_language_work import advance_ground_language
from tools.graph_native_dialogue import source


def main():
    parser = argparse.ArgumentParser(description='학습된 조각 그래프의 명시적 실행 예제')
    parser.add_argument('--ask', action='store_true')
    parser.add_argument('--non-interactive', action='store_true')
    args = parser.parse_args()
    base = json.loads((ROOT / 'examples/graph_native/ko-understanding.json').read_text())
    case = json.loads((ROOT / 'examples/graph_native/ko-compositional-example.json').read_text())
    program = json.loads((ROOT / 'programs/foundation-compositional-ko-experimental.json').read_text())
    strategy = json.loads((ROOT / 'programs/hypothesis-leaf-question-step.json').read_text())
    statements = [] if args.ask else [
        {'source': source('composition:statement:' + str(i), text), 'caller_attested': True}
        for i, text in enumerate(case['statements'])]
    inputs = (program, base['model'], strategy, base['rules'], statements,
              source('composition:query', case['query']), case['context_id'])
    result = advance_ground_language(*inputs)
    turn = 0
    while result['status'] == 'asking' and not args.non_interactive and turn < 2:
        print('MARCO:', result['text'])
        print('학습된 조각을 사용하는 전체 문장으로 답변하세요. 빈 입력은 종료합니다.')
        try:
            text = input('답변> ')
        except EOFError:
            break
        if not text:
            break
        turn += 1
        result = advance_ground_language(*inputs, session=result['session'], reply={
            'source': source('composition:reply:' + str(turn), text), 'caller_attested': True})
    print(json.dumps({'status': result['status'], 'answer': result.get('text'),
                      'reason': result.get('reason'), 'experimental': True,
                      'self_learning': False}, ensure_ascii=False, indent=2))
    return 0 if result['status'] in ('asking', 'confirmed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
