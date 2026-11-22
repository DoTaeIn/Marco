"""Find variants of the same connector from raw text, by counting.

Two word endings are taken as variants of one connector when raw text shows both:

  same job      they are followed by the same words (right contexts overlap), and each is
                the other's best match on that measure, by a clear ratio
  never rivals  they almost never follow the same character (left contexts are disjoint)

That is the pattern of 은/는 and 을/를: one connector whose form depends on the character
before it. Only endings of the same length, made of letters, are compared. Two endings that follow the same characters are different words,
however alike their contexts, and are never paired here.

Only blank space is assumed, to split text into words. No labels, no word list, no neural
model: the output is integer counts and example words, built offline.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

SCHEMA = 'graph-connector-variants-v1'
DEFAULT_POLICY = {'max_ending_chars': 2, 'kept_endings': 400, 'max_left_share': [1, 10],
                  'min_right_share': [1, 5], 'lead_ratio': [3, 2], 'min_count': 2000,
                  'min_distinct_before': 250}


def lines_of(path, field=None):
    """Text lines from a plain file, or one field of a JSON-lines file."""
    with open(path, encoding='utf8') as handle:
        for line in handle:
            if field:
                try:
                    line = json.loads(line).get(field) or ''
                except ValueError:
                    continue
            yield line


def count(lines, policy=None):
    """For the commonest word endings: which character comes before, which word comes after."""
    policy = dict(DEFAULT_POLICY, **(policy or {}))
    sizes = range(1, policy['max_ending_chars'] + 1)
    lines = list(lines)
    totals = collections.Counter()
    for line in lines:
        for word in line.split():
            for size in sizes:
                if len(word) > size:
                    totals[word[-size:]] += 1
    kept = {e for e, n in totals.most_common(policy['kept_endings']) if n >= policy['min_count']}
    left = {e: collections.Counter() for e in kept}
    right = {e: collections.Counter() for e in kept}
    for line in lines:
        words = line.split()
        for word, following in zip(words, words[1:]):
            for size in sizes:
                ending = word[-size:]
                if len(word) > size and ending in kept:
                    # Only letters count as "the character before": after a bracket, digit or
                    # quote the form is decided by a word that is not next to it.
                    if word[-size - 1].isalpha():
                        left[ending][word[-size - 1]] += 1
                    right[ending][following] += 1
    return {'totals': {e: totals[e] for e in kept}, 'left': left, 'right': right, 'policy': policy,
            'lines': len(lines)}


def _overlap(a, b):
    """Share of two count tables that coincides, each taken as proportions, in parts per thousand.

    Proportions make the measure independent of how common each ending is, so a rare ending
    cannot look like a frequent one just by being small.
    """
    total_a, total_b = sum(a.values()), sum(b.values())
    if not total_a or not total_b:
        return 0
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    size_small, size_large = (total_a, total_b) if small is a else (total_b, total_a)
    return round(1000 * sum(min(n / size_small, large[k] / size_large) for k, n in small.items() if k in large))


def pairs(counts):
    """Endings that do the same job and never follow the same character, each the other's best match."""
    policy, left, right = counts['policy'], counts['left'], counts['right']
    # A connector is made of letters only; an ending with a bracket or comma is a longer string.
    # ... and it attaches to almost any word, so many different characters come before it.
    endings = sorted(e for e in right if e.isalpha() and sum(right[e].values()) >= policy['min_count']
                     and len(left[e]) >= policy['min_distinct_before'])
    max_left = 1000 * policy['max_left_share'][0] // policy['max_left_share'][1]
    min_right = 1000 * policy['min_right_share'][0] // policy['min_right_share'][1]
    num, den = policy['lead_ratio']
    ranked = {}
    for a in endings:
        scored = []
        for b in endings:
            if a == b or len(a) != len(b):
                continue
            before = _overlap(left[a], left[b])
            if before > max_left:
                continue
            scored.append((_overlap(right[a], right[b]), b, before))
        scored.sort(reverse=True)
        if scored and scored[0][0] >= min_right and (len(scored) == 1 or scored[0][0] * den >= num * scored[1][0]):
            ranked[a] = scored[0] + (scored[1][0] if len(scored) > 1 else 0,)
    out = []
    for a, best in sorted(ranked.items()):
        b = best[1]
        if a < b and b in ranked and ranked[b][1] == a:
            common = sorted((w for w in right[a] if w in right[b]), key=lambda w: -min(right[a][w], right[b][w]))
            out.append({'forms': [a, b], 'same_following_per_thousand': best[0],
                        'next_best_per_thousand': max(best[3], ranked[b][3]),
                        'same_preceding_per_thousand': best[2],
                        'seen': {a: sum(right[a].values()), b: sum(right[b].values())},
                        'distinct_before': {a: len(left[a]), b: len(left[b])},
                        'examples_following': common[:8],
                        'examples_before': {a: [c for c, _ in left[a].most_common(6)],
                                            b: [c for c, _ in left[b].most_common(6)]}})
    return out


def build(path, field=None, policy=None):
    counts = count(lines_of(path, field), policy)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {'schema': SCHEMA, 'policy': counts['policy'], 'source': {'file': Path(path).name, 'sha256': digest,
                                                                     'lines': counts['lines'], 'field': field},
            'pairs': pairs(counts)}


def lookup(variants):
    """form -> its variant, for every pair."""
    table = {}
    for pair in (variants or {}).get('pairs', []):
        a, b = pair['forms']
        table[a], table[b] = (b, pair), (a, pair)
    return table


def check_against_lessons(variants, lessons):
    """Test each pair on lessons that show both forms: hide one form, read it through the other.

    For a pair whose two forms both occur in the lessons, every lesson containing one form is
    removed, a model is built from the rest plus the pair, and the removed lessons are read.
    A reading equal to the authored graph is `same`, a different one `different`, none `held`.
    Any `different` needs looking at before the pair is used. A pair the lessons cannot test is
    `untested`; one where every hidden lesson was held gives `no evidence`.
    """
    from experiments.graph_example_acquisition import v2
    from . import reader
    report = []
    for pair in variants.get('pairs', []):
        row = {'forms': pair['forms'], 'tests': []}
        for hidden in pair['forms']:
            mark = hidden + ' '
            removed = [ex for ex in lessons if mark in ex['text']]
            kept = [ex for ex in lessons if mark not in ex['text']]
            other = [f for f in pair['forms'] if f != hidden][0]
            if not removed or not any(other + ' ' in ex['text'] for ex in kept):
                continue
            model = reader.build(kept, variants={'pairs': [pair]})
            counts = {'same': 0, 'different': 0, 'held': 0}
            for ex in removed:
                result = reader.read(ex['text'], model)
                if result['status'] != 'complete':
                    counts['held'] += 1
                elif v2.canonical(result['graphs'][0]) == v2.canonical(ex['graph']):
                    counts['same'] += 1
                else:
                    counts['different'] += 1
            row['tests'].append(dict(counts, hidden=hidden, lessons=len(removed)))
        row['status'] = 'untested' if not row['tests'] else \
            'different readings' if any(t['different'] for t in row['tests']) else \
            'passed' if any(t['same'] for t in row['tests']) else 'no evidence'
        report.append(row)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--text', required=True)
    parser.add_argument('--field', help='field holding the text, for a JSON-lines file')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = build(args.text, args.field)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf8')
    for pair in result['pairs']:
        print(pair['forms'], 'following words alike: %d per thousand (next best %d); same preceding character: %d per thousand'
              % (pair['same_following_per_thousand'], pair['next_best_per_thousand'], pair['same_preceding_per_thousand']))


if __name__ == '__main__':
    main()
