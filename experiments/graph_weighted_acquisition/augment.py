"""Blind value substitution: scale teacher pairs by swapping named values.

Each passage/question pair is copied with every open value replaced by a name
drawn at random from an external pool. The draw never looks at parser output,
scores or failures. Structure, graph and evidence are unchanged; only value
text and the character offsets that follow from it move.

A replacement keeps the original's final-consonant class (none / rieul / other),
read from the Unicode code point, so the particle that follows stays well formed.
"""
import argparse
import copy
import json
import random
from pathlib import Path


def final_class(text):
    code = ord(text[-1]) - 0xAC00
    if not 0 <= code < 11172:
        return 'other-script'
    return {0: 'open', 8: 'rieul'}.get(code % 28, 'closed')


def load_names(path):
    words = []
    for line in Path(path).read_text(encoding='utf8').splitlines():
        if not line.startswith('#'):
            words.extend(line.split())
    return words


def _values(example):
    """Spans of open values: nodes whose whole anchor is an input copy."""
    anchors = {n['id']: n.get('anchor') for n in example['graph']['nodes']}
    return sorted({tuple(o['copy']) for s, p, o in example['graph']['edges']
                   if p == 'value' and isinstance(o, dict) and 'copy' in o and o['copy'] == anchors.get(s)})


def _rewrite(example, mapping, suffix):
    """Replace every occurrence of each original value, anchored or not.

    A person mentioned twice may carry one anchor only; the second mention sits in
    plain text and must change with the first or the copy contradicts itself.
    """
    text, wanted = example['text'], {tuple(s) for s in _values(example)}
    spans, pos = [], 0
    olds = sorted(mapping, key=len, reverse=True)
    while pos < len(text):
        hit = next((old for old in olds if text.startswith(old, pos)), None)
        if hit:
            spans.append((pos, pos + len(hit)))
            pos += len(hit)
        else:
            pos += 1
    if not wanted <= set(spans):
        raise ValueError('value span is not a clean occurrence of its text')
    pieces, moved, last, shift = [], {}, 0, 0
    for start, end in spans:
        new = mapping[text[start:end]]
        pieces += [text[last:start], new]
        moved[start] = start + shift
        shift += len(new) - (end - start)
        moved[end] = end + shift
        last = end
    pieces.append(text[last:])
    inside = {i for a, b in spans for i in range(a + 1, b)}

    def at(pos):
        if pos in moved:
            return moved[pos]
        if pos in inside:
            raise ValueError('span boundary inside a replaced value')
        return pos + sum(len(mapping[text[a:b]]) - (b - a) for a, b in spans if b <= pos)

    def span(s):
        return [at(s[0]), at(s[1])]

    out = copy.deepcopy(example)
    out['id'] = example['id'] + suffix
    out['text'] = ''.join(pieces)
    graph = out['graph']
    for node in graph['nodes']:
        if 'anchor' in node:
            node['anchor'] = span(node['anchor'])
    for edge in graph['edges']:
        if isinstance(edge[2], dict) and 'copy' in edge[2]:
            edge[2]['copy'] = span(edge[2]['copy'])
    graph['edge_spans'] = [[span(s) for s in ss] for ss in graph['edge_spans']]
    return out


def augment(dataset, names, copies, seed, keep_original=True):
    """Return a dataset with `copies` renamed versions of every pair."""
    rng = random.Random(seed)
    pools = {}
    for name in names:
        pools.setdefault(final_class(name), []).append(name)
    by_id = {ex['id']: ex for ex in dataset['examples']}
    examples = list(dataset['examples']) if keep_original else []
    pairs = list(dataset['pairs']) if keep_original else []
    seen = {ex['text'] for ex in examples}
    skipped = []
    for pair in dataset['pairs']:
        members = [by_id[pair['passage_id']], by_id[pair['question_id']]]
        originals = sorted({ex['text'][a:b] for ex in members for a, b in _values(ex)})
        for k in range(copies):
            suffix = '#%d' % k
            try:
                mapping, used = {}, set()
                for old in originals:
                    choices = [n for n in pools.get(final_class(old), []) if n not in used]
                    if not choices:
                        raise ValueError('no unused name with the same final class')
                    mapping[old] = rng.choice(choices)
                    used.add(mapping[old])
                new = [_rewrite(ex, mapping, suffix) for ex in members]
                if any(ex['text'] in seen for ex in new):
                    raise ValueError('duplicate text')
            except (ValueError, KeyError) as error:
                skipped.append({'pair': pair['id'], 'copy': k, 'reason': str(error)})
                continue
            seen.update(ex['text'] for ex in new)
            examples.extend(new)
            pairs.append(dict(pair, id=pair['id'] + suffix, passage_id=new[0]['id'], question_id=new[1]['id'],
                              expected_bindings=[[mapping.get(v, v) for v in row] for row in pair['expected_bindings']]))
    return {'examples': examples, 'pairs': pairs}, skipped


def split_names(names, seed):
    """Two disjoint halves: one for training copies, one for fresh test copies."""
    shuffled = sorted(set(names))
    random.Random(seed).shuffle(shuffled)
    half = len(shuffled) // 2
    return shuffled[:half], shuffled[half:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--names', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--copies', type=int, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--half', choices=('train', 'test'), required=True)
    parser.add_argument('--drop-original', action='store_true')
    args = parser.parse_args()
    train_names, test_names = split_names(load_names(args.names), args.seed)
    dataset = json.loads(Path(args.input).read_text(encoding='utf8'))
    result, skipped = augment(dataset, train_names if args.half == 'train' else test_names, args.copies,
                              args.seed, keep_original=not args.drop_original)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False) + '\n', encoding='utf8')
    print(json.dumps({'examples': len(result['examples']), 'pairs': len(result['pairs']), 'skipped': len(skipped)}))


if __name__ == '__main__':
    main()
