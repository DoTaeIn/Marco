"""Offline weight building and before/after comparison for count-weighted ranking.

Reports carry example ids, states and counts only. No text, graph or gold
content is written to a report.
"""
import argparse
import json
from pathlib import Path

from experiments.graph_example_acquisition import v2
from . import merge, weights as W


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def state(result, gold):
    """Where one parse stands against the authored graph."""
    keys = [v2.canonical(g) for g in result['graphs']]
    if result['status'] == 'complete':
        return 'correct' if keys[0] == gold else 'wrong'
    if result['status'] == 'ambiguous':
        return 'ambiguous_gold_present' if gold in keys else 'ambiguous_gold_absent'
    return result['status']


def compare(grammar, weights, examples, force_merge=False):
    rows = []
    for ex in examples:
        try:
            gold = v2.canonical(ex['graph'])
            before = v2.parse(ex['text'], grammar)
            after = W.rank(ex['text'], merge.expand(ex['text'], before, weights, force_merge), weights)
            rows.append({'id': ex['id'], 'kind': ex.get('kind'), 'before': state(before, gold),
                         'after': state(after, gold), 'margin': after['weighted'].get('margin'),
                         'reason': after['weighted'].get('reason')})
        except (ValueError, KeyError, TypeError) as error:
            rows.append({'id': ex.get('id'), 'kind': ex.get('kind'), 'before': 'error', 'after': 'error',
                         'reason': str(error)})
    return rows


def summarize(rows):
    transitions, before, after = {}, {}, {}
    for row in rows:
        name = row['before'] + ' -> ' + row['after']
        transitions[name] = transitions.get(name, 0) + 1
        before[row['before']] = before.get(row['before'], 0) + 1
        after[row['after']] = after.get(row['after'], 0) + 1
    return {'examples': len(rows), 'before': dict(sorted(before.items())), 'after': dict(sorted(after.items())),
            'transitions': dict(sorted(transitions.items())),
            'gold_lost': transitions.get('ambiguous_gold_present -> wrong', 0),
            'resolved_correct': transitions.get('ambiguous_gold_present -> correct', 0)}


def _policy(args):
    return {'alpha': [args.alpha_num, args.alpha_den], 'margin_ratio': args.margin_ratio,
            'require_support': not args.allow_unsupported}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('build', 'evaluate', 'loo'):
        p = sub.add_parser(name)
        p.add_argument('--train', required=True)
        p.add_argument('--output', required=True)
        p.add_argument('--alpha-num', type=int, default=W.DEFAULT_POLICY['alpha'][0])
        p.add_argument('--alpha-den', type=int, default=W.DEFAULT_POLICY['alpha'][1])
        p.add_argument('--margin-ratio', type=int, default=W.DEFAULT_POLICY['margin_ratio'])
        p.add_argument('--allow-unsupported', action='store_true')
        p.add_argument('--force-merge', action='store_true',
                       help='diagnostic only: merge repeated values without training evidence')
        if name == 'evaluate':
            p.add_argument('--eval', required=True)
    args = parser.parse_args()
    train = _load(args.train)['examples']
    if args.command == 'build':
        _write(args.output, W.build(train, _policy(args)))
        print('built')
        return
    if args.command == 'evaluate':
        grammar = v2.induce(train)['grammar']
        weights = W.build(train, _policy(args))
        rows = compare(grammar, weights, _load(args.eval)['examples'], args.force_merge)
        scope = 'weights and grammar from train; eval examples scored against their authored graphs'
    else:
        # Leave one out: grammar and counts never see the example they are scored on.
        rows = []
        for i, ex in enumerate(train):
            rest = train[:i] + train[i + 1:]
            rows.extend(compare(v2.induce(rest)['grammar'], W.build(rest, _policy(args)), [ex], args.force_merge))
        scope = 'leave-one-out over train; each example scored by a grammar and counts built without it'
    if args.force_merge:
        scope += '; DIAGNOSTIC forced merge, not a learned result'
    _write(args.output, {'version': 'graph-count-weights-report-v1', 'scope': scope, 'policy': _policy(args),
                         'summary': summarize(rows), 'rows': rows})
    print(json.dumps(summarize(rows), ensure_ascii=False))


if __name__ == '__main__':
    main()
