"""Optional source-attested graph-language bridge; no Python language grammar."""
import hashlib
import json

from marco.reasoning.graph_vm import MAXIMUM_BUDGET, run_recorded, validate_value
from marco.reasoning.proof_graph import verify_proof_graph
from marco.runtime.graph_route_work import advance_information_goal
from tools.graph_reasoning_audit import verify_vm_record

_ERRORS = (ValueError, TypeError, KeyError, UnicodeEncodeError, RecursionError)
_SCHEMA = 'marco-ground-language-session-v1'
_BAD = ('invalid_input', 'execution_error', 'invalid_history')
_LIMITATIONS = (
    'caller_attested source hashes prove structural source attribution only; they do not authenticate sources or establish real-world truth',
    'understanding is limited to what the supplied graph program and model declare; no arbitrary language claim',
)
_SESSION_KEYS = {'schema', 'context_id', 'pins', 'statements', 'query', 'replies', 'work', 'realization', 'limitations'}
_WORK_KEYS = ('status', 'reason', 'facts', 'pending_question', 'goal_record', 'goal_verification', 'transcript', 'asked', 'counts')


def _c(v):
    return json.loads(json.dumps(v))


def _digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _text(v, n):
    return type(v) is str and bool(v) and len(v) <= n


def _int(v, lo, hi):
    return type(v) is int and lo <= v <= hi


def _source(s):
    if (type(s) is not dict or s.keys() != {'id', 'text', 'sha256'} or not _text(s['id'], 64)
            or not _text(s['text'], 1024) or type(s['sha256']) is not str
            or hashlib.sha256(s['text'].encode('utf-8')).hexdigest() != s['sha256']):
        raise ValueError('source')
    return _c(s)


def _model(m):
    if type(m) is not dict or m.keys() != {'labels', 'labels_by_id', 'patterns'}:
        raise ValueError('model')
    labels, first = m['labels'], {}
    if type(labels) is not list or len(labels) > 8:
        raise ValueError('model')
    for lab in labels:
        if type(lab) is not dict or lab.keys() != {'id', 'text'} or not _text(lab['id'], 64) or not _text(lab['text'], 128):
            raise ValueError('model')
        first.setdefault(lab['id'], lab['text'])
    if m['labels_by_id'] != first:
        raise ValueError('model')
    pats = m['patterns']
    if type(pats) is not list or len(pats) > 12:
        raise ValueError('model')
    ids = set()
    for p in pats:
        if (type(p) is not dict or p.keys() != {'id', 'kind', 'relation', 'polarity', 'prefix', 'between', 'suffix'}
                or not _text(p['id'], 64) or p['id'] in ids or p['kind'] not in ('fact', 'query')
                or not _text(p['relation'], 128) or type(p['polarity']) is not bool
                or (p['kind'] == 'query' and p['polarity'] is not True)
                or any(type(p[k]) is not str or len(p[k]) > 128 for k in ('prefix', 'between', 'suffix'))):
            raise ValueError('model')
        ids.add(p['id'])
    validate_value(m)


def _env(program, model, ip, rules, statements, query, context_id, limits):
    if type(program) is not dict or type(ip) is not dict or not _text(context_id, 64):
        raise ValueError('input')
    if (not _int(limits['max_steps'], 1, 128) or not _int(limits['max_questions'], 0, 4)
            or not _int(limits['budget'], 1, MAXIMUM_BUDGET) or not _int(limits['trace_limit'], 1, 256)
            or not _int(limits['limit'], 1, 32) or not _int(limits['proof_limit'], 1, 4)
            or not _int(limits['search_limit'], 1, 256)):
        raise ValueError('limits')
    if type(statements) is not list or len(statements) > 32:
        raise ValueError('statements')
    sts = []
    for s in statements:
        if type(s) is not dict or s.keys() != {'source', 'caller_attested'} or s['caller_attested'] is not True:
            raise ValueError('statement')
        sts.append({'source': _source(s['source']), 'caller_attested': True})
    q = _source(query)
    ids = [s['source']['id'] for s in sts] + [q['id']]
    if len(set(ids)) != len(ids):
        raise ValueError('source_ids')
    m = _c(model)
    _model(m)
    return {'lp': _c(program), 'ip': _c(ip), 'model': m, 'rules': _c(rules), 'context': context_id,
            'limits': dict(limits), 'statements': sts, 'query': q, 'facts': None, 'target': None}


def _pins(env):
    return {'program': _digest(env['lp']), 'information_program': _digest(env['ip']),
            'model': _digest(env['model']), 'rules': _digest(env['rules']), 'limits': _digest(env['limits'])}


def _meaning(env, m):
    if (type(m) is not dict or m.keys() != {'kind', 'triple', 'polarity'} or m['kind'] not in ('fact', 'query')
            or type(m['polarity']) is not bool or (m['kind'] == 'query' and m['polarity'] is not True)):
        raise ValueError('meaning')
    t = m['triple']
    if type(t) is not list or len(t) != 3 or not all(_text(x, 128) and not x.startswith('?') for x in t):
        raise ValueError('meaning')
    ids = env['model']['labels_by_id']
    if t[0] not in ids or t[2] not in ids:
        raise ValueError('meaning_label')


def _hold(reason):
    return {'action': 'hold', 'state': None, 'meaning': None, 'text': None, 'reason': reason}


def _out(env, mode, text, meaning, out):
    if type(out) is not dict or out.keys() != {'action', 'state', 'meaning', 'text', 'reason'}:
        raise ValueError('output')
    act = out['action']
    if act not in ('continue', 'done', 'hold') or not _text(out['reason'], 128):
        raise ValueError('output')
    if out['state'] is not None:
        if type(out['state']) is not dict:
            raise ValueError('output')
        validate_value(out['state'])
    if act == 'done':
        _meaning(env, out['meaning'])
        if mode == 'parse':
            if out['text'] != text:
                raise ValueError('parse_text')
        elif not _text(out['text'], 1024) or _digest(out['meaning']) != _digest(meaning):
            raise ValueError('render_output')
    elif out['meaning'] is not None or out['text'] is not None:
        raise ValueError('output')


def _judge(env, mode, text, meaning, inputs, rec):
    L = env['limits']
    validate_value(inputs)
    if type(rec) is not dict or type(rec.get('record')) is not dict or type(rec.get('result')) is not dict:
        raise ValueError('receipt')
    validate_value(rec['record'])
    validate_value(rec['result'])
    if (rec['record'].get('budget') != L['budget'] or rec['record'].get('trace_limit') != L['trace_limit']
            or rec['record'].get('complete') is not True or rec['result'].get('status') != 'completed'):
        raise ValueError('receipt')
    v = verify_vm_record(_c(rec), _c(env['lp']), _c(inputs), max_budget=L['budget'])
    if type(v) is not dict or v.get('valid') is not True or v.get('execution_completed') is not True:
        raise ValueError('receipt_invalid')
    out = _c(rec['result'].get('value'))
    _out(env, mode, text, meaning, out)
    return out


def _drive(env, mode, text, meaning, saved):
    L = env['limits']
    state, steps, seen = None, [], set()
    for i in range(L['max_steps']):
        inputs = _c({'mode': mode, 'model': env['model'], 'text': text, 'meaning': meaning, 'state': state})
        if saved is None:
            validate_value(inputs)
            rec = _c(run_recorded(_c(env['lp']), inputs, budget=L['budget'], trace_limit=L['trace_limit']))
        else:
            if (i >= len(saved) or type(saved[i]) is not dict or saved[i].keys() != {'state', 'receipt'}
                    or _digest(saved[i]['state']) != _digest(state)):
                raise ValueError('lang_chain')
            rec = saved[i]['receipt']
        out = _judge(env, mode, text, meaning, inputs, rec)
        d = _digest(rec)
        if d in seen:
            raise ValueError('lang_repeat')
        seen.add(d)
        steps.append({'state': _c(state), 'receipt': _c(rec)})
        if out['action'] != 'continue':
            break
        if out['state'] is None or _digest(out['state']) == _digest(state):
            out = _hold('no_progress')
            break
        state = out['state']
    else:
        out = _hold('step_limit')
    if saved is not None and len(saved) != len(steps):
        raise ValueError('lang_trailing')
    return out, steps


def _lang(env, mode, text, meaning, saved=None):
    if saved is not None and (type(saved) is not dict or saved.keys() != {'steps', 'final', 'chain'}
                              or type(saved['steps']) is not list
                              or not 1 <= len(saved['steps']) <= env['limits']['max_steps']):
        raise ValueError('lang_record')
    out, steps = _drive(env, mode, text, meaning, None if saved is None else saved['steps'])
    rec = {'steps': steps, 'final': out, 'chain': _digest({'steps': steps, 'final': out})}
    if saved is not None and _digest(saved) != _digest(rec):
        raise ValueError('lang_mismatch')
    return out, rec


def _parse(env, src, saved=None):
    out, rec = _lang(env, 'parse', src['text'], None, saved)
    if out['action'] != 'done':
        raise ValueError('language_' + out['action'] + ':' + out['reason'][:64])
    return out['meaning'], rec


def _realize(env, meaning, saved=None):
    if saved is not None and (type(saved) is not dict or saved.keys() != {'meaning', 'text', 'render', 'parse'}
                              or _digest(saved['meaning']) != _digest(meaning)):
        raise ValueError('realization_record')
    r_out, r_rec = _lang(env, 'render', '', meaning, None if saved is None else saved['render'])
    if r_out['action'] != 'done':
        raise ValueError('render_' + r_out['action'])
    text = r_out['text']
    p_out, p_rec = _lang(env, 'parse', text, None, None if saved is None else saved['parse'])
    if p_out['action'] != 'done' or _digest(p_out['meaning']) != _digest(meaning):
        raise ValueError('roundtrip_mismatch')
    if saved is not None and saved['text'] != text:
        raise ValueError('realization_text')
    return {'meaning': _c(meaning), 'text': text, 'render': r_rec, 'parse': p_rec}


def _fact(src, m, chain):
    return {'id': 'src-' + _digest({'source_id': src['id'], 'sha256': src['sha256']})[:32],
            'triple': _c(m['triple']), 'polarity': m['polarity'], 'modality': 'asserted',
            'evidence': {'kind': 'caller_attested_source', 'source_id': src['id'], 'sha256': src['sha256'],
                         'caller_attested': True, 'language_chain': chain}}


def _build(env, saved_s=None, saved_q=None):
    if saved_s is not None and (type(saved_s) is not list or len(saved_s) != len(env['statements'])
                                or type(saved_q) is not dict or saved_q.keys() != {'source', 'parse'}
                                or _digest(saved_q['source']) != _digest(env['query'])):
        raise ValueError('session_sources')
    facts, ids, srecs = [], set(), []
    for i, st in enumerate(env['statements']):
        sv = None
        if saved_s is not None:
            sv = saved_s[i]
            if (type(sv) is not dict or sv.keys() != {'source', 'caller_attested', 'parse'}
                    or _digest(sv['source']) != _digest(st['source']) or sv['caller_attested'] is not True):
                raise ValueError('session_sources')
        m, rec = _parse(env, st['source'], None if sv is None else sv['parse'])
        if m['kind'] != 'fact':
            raise ValueError('statement_not_fact')
        f = _fact(st['source'], m, rec['chain'])
        if f['id'] in ids:
            raise ValueError('fact_collision')
        ids.add(f['id'])
        facts.append(f)
        srecs.append({'source': st['source'], 'caller_attested': True, 'parse': rec})
    m, qrec = _parse(env, env['query'], None if saved_q is None else saved_q['parse'])
    if m['kind'] != 'query' or m['polarity'] is not True:
        raise ValueError('query_not_query')
    env['facts'], env['target'] = facts, _c(m['triple'])
    return srecs, {'source': env['query'], 'parse': qrec}


def _advance(env, work, reply):
    return advance_information_goal(env['ip'], env['facts'], env['rules'], env['target'], env['context'],
                                    work=work, reply=reply, **env['limits'])


def _verify_replies(env, ses, work, seen):
    trs = [e['reply'] for e in work['transcript'] if e.get('kind') == 'reply']
    reps = ses['replies']
    if type(reps) is not list or len(reps) != len(trs) or len(reps) > 4:
        raise ValueError('replies')
    for rr, r in zip(reps, trs):
        if (type(rr) is not dict or rr.keys() != {'kind', 'source', 'caller_attested', 'parse', 'reply'}
                or rr['caller_attested'] is not True):
            raise ValueError('reply_record')
        src = _source(rr['source'])
        if src['id'] in seen:
            raise ValueError('reply_source_duplicate')
        seen.add(src['id'])
        if _digest(r) != _digest(rr['reply']) or r['source'] != src or r['context_id'] != env['context']:
            raise ValueError('reply_chronology')
        if rr['kind'] == 'natural':
            m, _ = _parse(env, src, rr['parse'])
            if (m['kind'] != 'fact' or r['triple'] != m['triple']
                    or r['outcome'] != ('positive' if m['polarity'] else 'negative')):
                raise ValueError('reply_parse_mismatch')
        elif rr['kind'] != 'structured' or rr['parse'] is not None or r['outcome'] != 'unknown':
            raise ValueError('reply_kind')


def _resume(env, ses):
    if type(ses) is not dict or ses.keys() != _SESSION_KEYS or ses['schema'] != _SCHEMA:
        raise ValueError('session_shape')
    if (ses['pins'] != _pins(env) or ses['context_id'] != env['context']
            or ses['limitations'] != list(_LIMITATIONS)):
        raise ValueError('session_pins')
    _build(env, ses['statements'], ses['query'])
    saved = ses['work']
    if type(saved) is not dict:
        raise ValueError('session_work')
    audited = _advance(env, _c(saved), None)
    if str(audited.get('reason')).startswith(_BAD):
        raise ValueError('work_invalid:' + str(audited.get('reason'))[:64])
    for k in _WORK_KEYS:
        if _digest(audited.get(k)) != _digest(saved.get(k)):
            raise ValueError('work_mismatch:' + k)
    seen = {s['source']['id'] for s in env['statements']} | {env['query']['id']}
    _verify_replies(env, ses, audited, seen)
    expected = _expected(env, audited)
    if ses['realization'] is not None:
        if expected is None:
            raise ValueError('unexpected_realization')
        _realize(env, expected, ses['realization'])
    elif expected is not None:
        raise ValueError('missing_saved_realization')
    return _c(ses), audited


def _apply_reply(env, ses, work, reply):
    p = work['pending_question'] if work['status'] == 'asking' else None
    if type(p) is not dict or type(reply) is not dict:
        raise ValueError('no_pending_question_or_bad_reply')
    seen = {s['source']['id'] for s in env['statements']} | {env['query']['id']}
    seen |= {r['source']['id'] for r in ses['replies']}
    if reply.keys() == {'source', 'caller_attested'}:
        if reply['caller_attested'] is not True:
            raise ValueError('attestation')
        src = _source(reply['source'])
        if src['id'] in seen:
            raise ValueError('reply_source_duplicate')
        m, rec = _parse(env, src)
        if m['kind'] != 'fact' or m['triple'] != p['triple']:
            raise ValueError('reply_mismatch')
        structured = {'question_id': p['id'], 'context_id': env['context'], 'triple': _c(p['triple']),
                      'outcome': 'positive' if m['polarity'] else 'negative', 'source': _c(src),
                      'caller_attested': True}
        rrec = {'kind': 'natural', 'source': src, 'caller_attested': True, 'parse': rec, 'reply': structured}
    elif reply.keys() == {'question_id', 'context_id', 'triple', 'outcome', 'source', 'caller_attested'}:
        structured = _c(reply)
        src = _source(structured['source'])
        if (structured['outcome'] != 'unknown' or structured['caller_attested'] is not True
                or structured['question_id'] != p['id'] or structured['context_id'] != env['context']
                or structured['triple'] != p['triple'] or src['id'] in seen):
            raise ValueError('structured_reply_rejected')
        rrec = {'kind': 'structured', 'source': src, 'caller_attested': True, 'parse': None, 'reply': structured}
    else:
        raise ValueError('reply_shape')
    old = sum(1 for e in work['transcript'] if e.get('kind') == 'reply')
    new = _advance(env, _c(work), structured)
    rs = [e for e in new.get('transcript', []) if type(e) is dict and e.get('kind') == 'reply']
    if (new.get('reply_rejection') is not None or len(rs) != old + 1
            or _digest(rs[-1]['reply']) != _digest(structured) or str(new.get('reason')).startswith(_BAD)):
        raise ValueError('underlying_rejected:' + str(new.get('reply_rejection'))[:64])
    ses = _c(ses)
    ses['replies'].append(rrec)
    return ses, new


def _expected(env, work):
    if work['status'] == 'asking' and type(work['pending_question']) is dict:
        return {'kind': 'query', 'triple': _c(work['pending_question']['triple']), 'polarity': True}
    if work['status'] == 'confirmed' and type(work['goal_record']) is dict:
        v = verify_proof_graph(_c(work['goal_record']), _c(work['facts']), _c(env['rules']), _c(env['target']))
        if (type(v) is dict and v.get('valid') is True and v.get('conclusion_verified') is True
                and work['goal_record'].get('status') == 'proved'):
            return {'kind': 'fact', 'triple': _c(env['target']), 'polarity': True}
    return None


def _final(env, ses, work, live):
    exp, real, why = _expected(env, work), None, str(work.get('reason'))
    if exp is not None:
        if live:
            try:
                _meaning(env, exp)
                real = _realize(env, exp)
            except _ERRORS as exc:
                why = 'realization_unverified:' + str(exc)[:80]
        elif ses['realization'] is not None:
            real = _realize(env, exp, ses['realization'])
        else:
            why = 'realization_unverified'
    elif work['status'] != 'held':
        why = 'unverifiable_state'
    ses['work'], ses['realization'] = work, real
    status = 'held' if real is None else work['status']
    return {'status': status, 'text': None if real is None else real['text'], 'session': ses,
            'information_work': work, 'reason': why, 'limitations': list(_LIMITATIONS)}


def advance_ground_language(program, model, information_program, rules, statements, query, context_id, *,
                            session=None, reply=None, max_steps=128, max_questions=2, budget=4096,
                            trace_limit=256, limit=32, proof_limit=4, search_limit=256):
    def held(reason, ses=None, work=None):
        return {'status': 'held', 'text': None, 'session': ses, 'information_work': work, 'reason': reason,
                'limitations': list(_LIMITATIONS)}

    limits = {'max_questions': max_questions, 'max_steps': max_steps, 'budget': budget,
              'trace_limit': trace_limit, 'limit': limit, 'proof_limit': proof_limit,
              'search_limit': search_limit}
    try:
        env = _env(program, model, information_program, rules, statements, query, context_id, limits)
    except _ERRORS as exc:
        return held('invalid_input:' + str(exc)[:96])
    try:
        if session is None:
            if reply is not None:
                return held('reply_without_session')
            srecs, qrec = _build(env)
            work = _advance(env, None, None)
            if str(work.get('reason')).startswith(_BAD):
                return held(str(work.get('reason')), None, work)
            ses = {'schema': _SCHEMA, 'context_id': env['context'], 'pins': _pins(env), 'statements': srecs,
                   'query': qrec, 'replies': [], 'work': None, 'realization': None,
                   'limitations': list(_LIMITATIONS)}
            live = True
        else:
            ses, work = _resume(env, session)
            live = False
    except _ERRORS as exc:
        return held(('ground_failed:' if session is None else 'invalid_session:') + str(exc)[:96])
    try:
        if reply is not None:
            try:
                ses2, work2 = _apply_reply(env, ses, work, reply)
            except _ERRORS as exc:
                return held('reply_rejected:' + str(exc)[:96], ses, work)
            ses, work, live = ses2, work2, True
        return _final(env, ses, work, live)
    except _ERRORS as exc:
        return held('invalid_session:' + str(exc)[:96])
