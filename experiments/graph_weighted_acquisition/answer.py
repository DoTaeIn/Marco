"""Answer a question from a passage and report exactly why.

Reading is done by the piece reader. The answer comes from matching the question
graph against the passage graph (match.py). The older native executor is run as
a second opinion and must agree whenever it finishes. No answer is given unless
both texts were read with a clear, fully observed lead and every condition of
the question is grounded in passage text.
"""
import argparse
import json
from pathlib import Path

from experiments.graph_example_acquisition import native
from experiments.graph_language_repair.questions.query_graph import execute_query_graph
from . import learn as L
from . import match as M
from . import reader as R
from . import write as W


def answer(passage, question, model, memory=None):
    """Read the passage and the question, then answer from the passage's graph.

    `memory` (see learn.py) holds words told in conversation. It is read through an overlay;
    neither it nor the model is changed here, except that uses of a stored word are logged.
    """
    lessons_only, model = model, L.overlay(model, memory)
    p = R.read(passage, model)
    out = _blank(p, None)
    if p['status'] != 'complete':
        out['reason'] = 'the passage was not read with confidence: ' + p['reason']
        out['question'] = R.read(question, model)
        return out
    if p.get('ignored'):
        out['reason'] = 'the passage could only be read by ignoring %s; a passage is never answered from part of it' \
            % ', '.join('"%s"' % x for x in p['ignored'])
        out['question'] = R.read(question, model)
        return out
    return answer_graph(p['graphs'][0], passage, question, lessons_only, p, memory)


def _blank(passage_result, question_result):
    return {'passage': passage_result, 'question': question_result, 'answers': [], 'status': 'hold', 'evidence': [],
            'verified': False, 'executor': 'not run', 'executor_detail': '', 'partial': [], 'claim': None,
            'raw_text_variants': [], 'unknown_words': [], 'told_words': [], 'proposals': [], 'sentences': [],
            'other_names': []}


def _claim_query(graph, text, predicate='claim'):
    """Turn "is X's P really V?" into "what is X's P?" plus the value that was claimed.

    Convention (named in the pack): an edge with the claim predicate marks a yes/no check, and the value mention
    standing right before the claim word is the one being checked.
    """
    marks = [(s, o) for s, p, o in graph['edges'] if p == predicate and isinstance(o, str)]
    if len(marks) != 1:
        return None
    anchors = {n['id']: n.get('anchor') for n in graph['nodes']}
    word = marks[0][1]
    named = [s for s, p, o in graph['edges'] if p == 'value' and anchors[s] and anchors[s][1] <= anchors[word][0]]
    if not named:
        return None
    checked = max(named, key=lambda n: anchors[n][1])
    keep = [(e, sp) for e, sp in zip(graph['edges'], graph['edge_spans'])
            if e[1] != predicate and not (e[0] == checked and e[1] == 'value')]
    query = {'nodes': [n for n in graph['nodes'] if n['id'] != word], 'edges': [e for e, _ in keep],
             'edge_spans': [sp for _, sp in keep], 'project': [checked]}
    return query, text[slice(*anchors[checked])]


def answer_graph(pgraph, ptext, question, model, passage_result=None, memory=None, aliases=None):
    """Answer a question from a given passage graph. Used by both arms."""
    lessons_only, model = model, L.overlay(model, memory)
    q = R.read(question, model)
    out = _blank(passage_result, q)
    if q['status'] != 'complete':
        out['reason'] = 'the question was not read with confidence: ' + q['reason']
        if q.get('attachment'):
            out['attachment'] = q['attachment']          # what to ask back, when the form leaves a part's place open
        if q.get('unknown_words'):
            # A word that the passage also uses as a name is a name; the rest are the suspects.
            named = {ptext[slice(*o['copy'])] for s, p, o in pgraph['edges']
                     if p == 'value' and isinstance(o, dict) and 'copy' in o}
            out['unknown_words'] = [w for w in q['unknown_words'] if w not in named]
            if out['unknown_words']:
                out['reason'] = 'the question contains a word the reader does not know: %s. The sentence is ' \
                                'closed like one that %s, and it does so only if that word is not a name' \
                                % (', '.join('"%s"' % w for w in out['unknown_words']), q['expected'])
                out['proposals'] = L.propose(lessons_only, memory, question, out['unknown_words'], R.read)
        return out
    conventions = R.recipe_of(model)[1]
    query, claimed = q['graphs'][0], None
    if not query['project']:
        turned = _claim_query(query, question, conventions['claim_predicate'])
        if not turned:
            out['reason'] = 'the question does not ask for anything the reader recognises'
            return out
        query, claimed = turned
    found = M.match(pgraph, ptext, query, question, aliases=aliases, rules=conventions['name_matching'])
    out['match'], out['query'] = found, query
    if found['status'] != 'answered':
        out['reason'] = found['reason']
        return out
    out['raw_text_variants'] = sorted(set(q.get('variants', [])) | set((passage_result or {}).get('variants', [])))
    told = {x['word']: x for x in q.get('told', []) + (passage_result or {}).get('told', [])}
    out['told_words'] = [told[w] for w in sorted(told)]
    if memory is not None and told:
        L.record_use(memory, sorted(told), question)
    for text in q.get('ignored', []):
        out['partial'].append('words in the question were ignored: "%s"' % text)
    out['other_names'] = ['"%s" is another name for "%s" (word pack)' % (n['asked'], n['matched'])
                          for n in found['notes'] if n.get('alias')]
    for note in found['notes']:
        if note.get('alias'):
            continue
        if note['level'] == 1:
            out['partial'].append('"%s" was taken as "%s" (spacing differs)' % (note['asked'], note['matched']))
        else:
            out['partial'].append('"%s" was taken as "%s"; the words "%s" in front of it were ignored'
                                  % (note['asked'], note['matched'], note['ignored']))
    spans = sorted({tuple(s) for proof in found['proofs'] for fact in proof['facts'] for s in fact['spans']})
    out['evidence'] = [{'span': list(s), 'text': ptext[s[0]:s[1]]} for s in spans]
    passed_over = q.get('ignored') or [n for n in found['notes'] if n['level'] == 2]
    if passed_over and conventions.get('partial_answers') == 'withhold':
        # Words of the question were passed over, and they may be the ones that change the answer
        # ("주말 운영시간" read as "운영시간"). The pack says such an answer is not given.
        out['reason'] = 'the question could only be answered by passing over part of it: ' + '; '.join(out['partial'])
        out['withheld'] = found['answers']
        return out
    if found['relaxed'] == 0 and not out['other_names']:
        check = _second_opinion(pgraph, ptext, query, question, found['answers'], conventions['executor_search_stops'])
    else:
        # The older executor compares names exactly, so it has nothing to say about a loose match.
        check = {'state': 'not comparable',
                 'detail': 'names were matched loosely or through another name, which the older executor cannot do'}
    out['executor'], out['executor_detail'] = check['state'], check['detail']
    out['verified'] = check['state'] == 'agrees' and not out['partial'] and not out['told_words']
    if check['state'] in ('disagrees', 'refuses'):
        # The second method finished and did not confirm: that is a hold, never an answer.
        out['reason'] = 'the second answer method %s: %s' % (check['state'], check['detail'])
        out['withheld'] = found['answers']
        return out
    if claimed is not None:
        out['claim'] = {'claimed': claimed, 'holds': found['answers'] == [[claimed]]}
    # The answer as a full sentence: the question's meaning with the answer put in, written from
    # the same counts and kept only if the reader reads it back as that meaning.
    out['sentences'] = W.answer_sentences(model, query, question, found['answers'], found['notes'])
    out.update(status='answered', answers=found['answers'],
               reason=found['reason'] + ('' if out['verified'] else '; not independently verified')
               + ('; partial reading' if out['partial'] else ''))
    return out


def _second_opinion(pgraph, ptext, qgraph, qtext, answers, search_stops):
    """Ask the older executor. Its own refusals count as refusals, not as silence.

    agrees      it finished with the same answers
    disagrees   it finished with different answers, or found nothing
    refuses     it stopped for a safety reason of its own
    unavailable it ran out of search budget, so nothing was checked

    The executor's own stop is classified first and is final. A separate search is
    consulted only to tell a budget stop from other holds, and only when the executor
    itself stopped inside a search; it can never turn a refusal into "unavailable".
    """
    result = native.run_pair(pgraph, ptext, qgraph, qtext, [])
    if 'actual' in result:
        if result.get('provenance_gaps') or result.get('ungrounded'):
            return {'state': 'refuses', 'detail': 'its evidence is incomplete'}
        same = result['actual'] == answers
        return {'state': 'agrees' if same else 'disagrees',
                'detail': 'same answers' if same else 'it answered %s' % result['actual']}
    reason = str(result.get('reason'))
    if result.get('status') == 'no_evidence':
        return {'state': 'disagrees', 'detail': 'it found no match'}
    if reason not in search_stops or result.get('status') != 'hold':
        return {'state': 'refuses', 'detail': reason}
    if str(result.get('detail', '')).endswith('_limit'):
        return {'state': 'unavailable', 'detail': 'search budget reached (%s)' % result['detail']}
    try:
        reading, program = native.compile_pair(pgraph, ptext, qgraph, qtext)
        raw = execute_query_graph(reading, program)
    except (KeyError, TypeError, ValueError) as error:
        return {'state': 'refuses', 'detail': str(error)}
    if raw.get('status') == 'hold' and str(raw.get('reason')).endswith('_limit'):
        return {'state': 'unavailable', 'detail': 'search budget reached (%s)' % raw['reason']}
    return {'state': 'refuses', 'detail': reason}


# ---------------------------------------------------------------- report

def _obj(graph, text, value):
    if isinstance(value, dict):
        return '"%s"' % value['literal'] if 'literal' in value else '"%s"' % text[slice(*value['copy'])]
    node = next(n for n in graph['nodes'] if n['id'] == value)
    named = [text[slice(*o['copy'])] for s, p, o in graph['edges'] if s == value and p == 'value']
    if named:
        return '"%s"' % named[0]
    return 'the thing asked for' if value in graph['project'] else '"%s"' % text[slice(*node['anchor'])]


def _facts(graph, text):
    lines = []
    for node in graph['nodes']:
        edges = [(p, o) for s, p, o in graph['edges'] if s == node['id'] and p != 'value']
        if edges:
            parts = ', '.join('%s = %s' % (p, _obj(graph, text, o)) for p, o in edges)
            lines.append('- %s "%s": %s' % (node['type'], text[slice(*node['anchor'])], parts))
    return lines


def _pieces(reading):
    names = {'gap': 'connector', 'value': 'name', 'head': 'fixed word', 'closed': 'fixed word', 'skip': 'IGNORED'}
    return ' '.join('[%s|%s]' % (p['text'], names[p['kind']]) for p in reading['pieces'] if p['text'])


def _plain(decision):
    """Show a stored label in words instead of raw JSON."""
    try:
        value = json.loads(decision)
    except (TypeError, ValueError):
        return str(decision).strip() or '(none)'
    if isinstance(value, dict):
        parts = [value.get('type', '')] + ['%s=%s' % (p, v) for p, v in value.get('literals', [])]
        if value.get('project'):
            parts.append('asked for')
        return ', '.join(x for x in parts if x)
    if isinstance(value, list):
        return ' + '.join(map(str, value)) or '(none)'
    return str(value)


def _sources(term):
    """Training example ids behind a count, plus the word forms a stem or ending came from."""
    ids = ', '.join(term['origins'][:3]) or '-'
    forms = term.get('forms') or []
    return ids + (' (from word forms %s)' % ', '.join(forms[:4]) if forms else '')


def _decisions(reading):
    rows, unused, routine = [], [], 0
    for t in reading['terms']:
        if t['what'] == 'known piece left unused':
            unused.append(t)
            continue
        if t['what'] in ('known piece used as structure', 'what follows this piece') or \
                t['what'].startswith('connecting piece'):
            routine += 1
            if t['count'] > 0:
                continue
        rows.append('| %s | %s | %s | %s | %d of %d | %s |' % (
            t['piece'].strip() or '(none)', t['what'], _plain(t['decision']),
            _plain(t['given']) if t['given'].startswith('{') else repr(t['given']), t['count'], t['of'], _sources(t)))
    lines = ['| Piece | Decision about | Chosen | Given | Seen in training | Example ids |',
             '|---|---|---|---|---|---|'] + rows
    lines.append('')
    longer = sorted({t['piece'] for t in reading['terms'] if t.get('graded') and t['count'] == 0})
    if longer:
        lines.append('Names of a length not seen in training: %s. This is allowed; it lowers the score and does '
                     'not block the reading.' % ', '.join('"%s"' % x for x in longer))
    lines.append('%d routine sequence checks also passed (each connector and what follows it was seen before).'
                 % routine)
    risky = [t for t in unused if t['count'] == 0]
    if unused:
        lines.append('%d known pieces occur in the text without being used as structure; %d of those were '
                     'never left unused in training%s.' % (len(unused), len(risky),
                     ': ' + ', '.join(sorted({repr(t['piece']) for t in risky})) if risky else ''))
    return lines


def _reading_section(title, result, text):
    lines = ['## ' + title, '', 'Text: `%s`' % text, '', 'Status: **%s** (%s).' % (result['status'], result['reason']), '']
    if not result['readings']:
        return lines + ['No way was found to cut this text into pieces seen in training.', '']
    chosen = result['readings'][result.get('chosen', 0)]
    lines += ['Pieces: ' + _pieces(chosen), '', 'What it means:'] + _facts(chosen['graph'], text) + ['']
    if chosen['graph']['project']:
        asked = [p for s, p, o in chosen['graph']['edges'] if o in chosen['graph']['project']]
        lines += ['Asked for: the ' + ' and '.join(asked) + ' of that event.', '']
    if chosen.get('merged'):
        lines += ['A name that appears twice was treated as one person, as training showed.', '']
    lines += ['Why each piece was read this way:', ''] + _decisions(chosen) + ['']
    rivals = [r for r in result['readings'] if r is not chosen]
    lines.append('Score %.2f, every piece seen in training: %s.' % (chosen['score'], 'yes' if chosen['supported'] else 'no'))
    if result.get('margin') is None:
        lines.append('No other reading has every piece seen in training, so there is no lead to report.')
    else:
        lines.append('Lead over the next fully seen reading: %.2f (required %.2f).' % (result['margin'], result['required_margin']))
    if result.get('unseen_lead') is not None and result['unseen_lead'] > 0:
        lines.append('A reading with an unseen piece scores %.2f higher than the chosen one.' % result['unseen_lead'])
    if result.get('cut_between_equals'):
        lines.append('The search dropped at least one candidate that scored the same as one it kept.')
    for rival in rivals[:2]:
        weak = sorted((t for t in rival['terms'] if t['count'] == 0), key=lambda t: t['log'])[:2]
        why = '; '.join('%s %r' % (t['what'], t['piece']) for t in weak) or 'lower counts for the same pieces'
        lines.append('- Rival (score %.2f): %s. Rejected because: %s.' % (rival['score'], _pieces(rival), why))
    return lines + ['']


def explain(passage, question, result):
    """A full plain-text account of how the answer was reached, or why none was given."""
    if result['status'] == 'answered':
        shown = '; '.join(', '.join(row) for row in result['answers'])
        if result['claim']:
            said = result['claim']['claimed']
            shown = ('Yes, %s' % shown) if result['claim']['holds'] else 'No. The passage says %s, not %s' % (shown, said)
        flags = (['partial reading'] if result['partial'] else []) + (['uses raw-text variants'] if result['raw_text_variants'] else []) \
            + (['uses words told in conversation'] if result['told_words'] else []) + ([] if result['verified'] else ['not independently verified'])
        head = ['# Answer: %s%s' % (shown, ' (%s)' % '; '.join(flags) if flags else ''), '']
        said = [x for x in result['sentences'] if x['status'] == 'said']
        if said:
            head += ['## Answer as a sentence', ''] + ['> ' + x['text'] for x in said] + ['']
            head += ['Each sentence was built from pieces seen in the lessons and then read back by the reader, '
                     'which had to arrive at the same meaning. How the first one was built:', '',
                     '| Piece | Why it was chosen |', '|---|---|']
            head += ['| %s | %s |' % (x['piece'].strip() or '(none)', x['why']) for x in said[0]['steps']] + ['']
        for x in result['sentences']:
            if x['status'] != 'said':
                head += ['No sentence was written for %s: %s.' % (', '.join(x['answer']), x['reason']), '']
        if result['told_words']:
            head += ['Read with words told in conversation, not taught by a lesson:', '']
            head += ['- "%s": %s, confirmed by %s' % (x['word'], x['status'], ', '.join(x['confirmed_by']))
                     for x in result['told_words']] + ['']
        if result['other_names']:
            head += ['Names matched through the word pack:', ''] + ['- ' + x for x in result['other_names']] + ['']
        if result['raw_text_variants']:
            head += ['Read with help from raw text, not from a lesson:', '']
            head += ['- ' + note for note in result['raw_text_variants']] + ['']
        if result['partial']:
            head += ['**Partial reading.** This answer rests on the following, which training does not back:', '']
            head += ['- ' + note for note in result['partial']] + ['']
    else:
        head = ['# No answer given', '', 'Reason: %s.' % result['reason'], '']
        if result.get('unknown_words'):
            head += ['## Unknown word', '',
                     'Not known to the reader: %s.' % ', '.join('"%s"' % w for w in result['unknown_words']), '',
                     'It was not read as a name, because the question would then ask for nothing. Nothing was '
                     'guessed about its meaning. Telling the reader what it means (a lesson, or a confirmed '
                     'answer to "is this a name or a question word?") would let this question be read.', '']
            if result.get('proposals'):
                head += ['Question to put to the user:', ''] + ['- ' + x['ask'] for x in result['proposals']] + ['']
        if result.get('withheld'):
            head += ['The matcher found %s, with passage text %s, but the answer was withheld.' % (
                '; '.join(', '.join(row) for row in result['withheld']),
                ', '.join('"%s"' % e['text'] for e in result['evidence'])), '']
    head += ['Question: `%s`' % question, '', 'Passage: `%s`' % passage, '']
    if result['status'] == 'answered':
        head += ['## Why this answer', '',
                 'The question was turned into a small graph with one unknown. The passage graph was searched '
                 'for a place where every condition of the question holds. The unknown there is the answer.', '']
        for n, proof in enumerate(result['match']['proofs'], 1):
            head += ['Ground %d for the answer %s, each condition and the passage text that satisfies it:'
                     % (n, ', '.join(proof['answer'])), '',
                     '| Condition in the question | Passage text |', '|---|---|']
            for fact in proof['facts']:
                s, p, o = fact['condition']
                if p == 'answer name':
                    label = 'the name of what was asked for'
                elif p == 'value':
                    label = 'a name given in the question: %s' % _obj(result['query'], question, o)
                else:
                    label = '%s = %s' % (p, _obj(result['query'], question, o))
                head.append('| %s | %s |' % (label, ' + '.join('"%s"' % t for t in fact['text'])))
            head.append('')
        if result['claim']:
            head += ['This was a yes/no question. It was answered by looking up the value and comparing it with '
                     'the claimed "%s".' % result['claim']['claimed'], '']
        if result['verified']:
            head += ['Verified: the older executor reached the same answer independently.', '']
        elif result['executor'] == 'agrees':
            head += ['The older executor reached the same answer, but the reading was partial, so this is not '
                     'counted as verified.', '']
        else:
            head += ['**Not independently verified.** The older executor could not check this answer: %s.'
                     % result['executor_detail'], '']
    body = _reading_section('How the passage was read', result['passage'], passage)
    body += _reading_section('How the question was read', result['question'], question)
    tail = ['## Method', '',
            '- Reading uses integer counts from training examples only. No neural network, embedding or token prediction.',
            '- A reading is accepted only if every piece was seen in training and it leads clearly.',
            '- The answer comes from matching the question graph against the passage graph; nothing is generated.',
            '- If a passage event fits the question but does not name what was asked for, no answer is given.', '']
    return '\n'.join(head + body + tail)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', help='teacher examples to build the model from')
    parser.add_argument('--model', help='a model file written earlier with --save-model')
    parser.add_argument('--save-model')
    parser.add_argument('--passage', required=True)
    parser.add_argument('--question', required=True)
    args = parser.parse_args()
    if args.model:
        model = json.loads(Path(args.model).read_text(encoding='utf8'))
    else:
        model = R.build(json.loads(Path(args.train).read_text(encoding='utf8'))['examples'])
    if args.save_model:
        Path(args.save_model).write_text(json.dumps(model, ensure_ascii=False) + '\n', encoding='utf8')
    print(explain(args.passage, args.question, answer(args.passage, args.question, model)))


if __name__ == '__main__':
    main()
