"""Bounded, character-span grammar induction; no language-specific knowledge."""
from __future__ import annotations
from copy import deepcopy
from itertools import permutations
import json

MAX_NODES = 8
MAX_MATCHES = 256
MAX_TEMPLATES = 128
REQUIRED_PERTURBATIONS = {'person', 'role', 'negation', 'source'}


def _stable(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def validate(example):
    text=example['text']; graph=example['graph']; nodes=graph['nodes']; edges=graph['edges']
    if not isinstance(text,str) or example['kind'] not in ('passage','question'): raise ValueError('invalid example')
    if not nodes or len(nodes)>MAX_NODES: raise ValueError('node bound')
    ids=[n['id'] for n in nodes]
    if len(set(ids))!=len(ids): raise ValueError('duplicate node')
    spans=[]
    for n in nodes:
        if set(n)-{'id','type','anchor'} or not isinstance(n['type'],str): raise ValueError('unknown node field')
        if 'anchor' in n:
            a=n['anchor']
            if not isinstance(a,list) or len(a)!=2 or not all(type(v) is int for v in a) or not 0<=a[0]<a[1]<=len(text): raise ValueError('invalid anchor')
            spans.append(tuple(a))
    spans.sort()
    if not spans or any(a[1]>b[0] for a,b in zip(spans,spans[1:])): raise ValueError('anchors must be nonoverlapping and present')
    seen=set()
    for edge in edges:
        if not isinstance(edge,list) or len(edge)!=3 or edge[0] not in ids or not isinstance(edge[1],str): raise ValueError('invalid edge')
        obj=edge[2]
        if isinstance(obj,dict):
            if set(obj)!={'literal'} or not isinstance(obj['literal'],str): raise ValueError('invalid typed literal')
            # Surface answer copying is not a legitimate unanchored semantic constant.
            if obj['literal'] and obj['literal'] in text: raise ValueError('surface literal must be represented by an anchored node')
        elif obj not in ids: raise ValueError('unknown edge endpoint')
        key=_stable(edge)
        if key in seen: raise ValueError('duplicate edge')
        seen.add(key)
    return example


def canonical(graph):
    """ID-invariant exact graph equality; bounded exhaustive node renaming."""
    nodes=graph['nodes']; ids=[n['id'] for n in nodes]
    if len(ids)>MAX_NODES: raise ValueError('node bound')
    labels=[{k:v for k,v in n.items() if k!='id'} for n in nodes]
    groups={}
    for i, lab in enumerate(labels): groups.setdefault(_stable(lab),[]).append(i)
    # Only equal labels can exchange places in the lexicographically minimal form.
    ordered=[groups[k] for k in sorted(groups)]
    from itertools import product
    best=None
    for choices in product(*(list(permutations(g)) for g in ordered)):
        order=[i for group in choices for i in group]; rename={ids[i]:str(j) for j,i in enumerate(order)}
        ns=[labels[i] for i in order]
        es=sorted([[rename[a],p,rename[b] if isinstance(b,str) else b] for a,p,b in graph['edges']],key=_stable)
        key=_stable({'nodes':ns,'edges':es})
        if best is None or key<best: best=key
    return best


def _fragment(example):
    validate(example); text=example['text']; nodes=example['graph']['nodes']; anchored=sorted((n for n in nodes if 'anchor' in n),key=lambda n:n['anchor'])
    # IDs never enter a production. Each anchor becomes an independently bounded hole.
    rest=sorted((n for n in nodes if 'anchor' not in n),key=lambda n:(n['type'],n['id']))
    order=anchored+rest; ids={n['id']:'n%d'%i for i,n in enumerate(order)}
    gaps=[]; end=0
    for n in anchored:
        a,b=n['anchor']; gaps.append(text[end:a]); end=b
    gaps.append(text[end:])
    outnodes=[{'id':ids[n['id']],'type':n['type'],**({'slot':i} if 'anchor' in n else {})} for i,n in enumerate(order)]
    edges=sorted([[ids[a],p,ids[b] if isinstance(b,str) else deepcopy(b)] for a,p,b in example['graph']['edges']],key=_stable)
    return {'gaps':gaps,'nodes':outnodes,'edges':edges}


def _matches(text, gaps, bound=MAX_MATCHES):
    if not text.startswith(gaps[0]): return [],True
    results=[]; truncated=False
    def rec(i, start, spans):
        nonlocal truncated
        if len(results)>=bound: truncated=True; return
        suffix=gaps[i+1]
        if i==len(gaps)-2:
            end=len(text)-len(suffix)
            if end>start and text[end:]==suffix: results.append(spans+[[start,end]])
            return
        # Every position is tried, including empty fixed separators; holes are nonempty.
        for end in range(start+1,len(text)+1):
            if text.startswith(suffix,end): rec(i+1,end+len(suffix),spans+[[start,end]])
            if truncated: return
    rec(0,len(gaps[0]),[])
    return results,not truncated


def parse(text, grammar, max_matches=MAX_MATCHES):
    outputs={}; complete=True; derivations=[]
    for rule in grammar['rules']:
        matches,done=_matches(text,rule['fragment']['gaps'],max_matches)
        complete &= done
        for spans in matches:
            f=rule['fragment']
            if any(allowed is not None and text[a:b] not in allowed for (a,b),allowed in zip(spans,rule['slot_values'])): continue
            nodes=[]
            for n in f['nodes']:
                node={'id':n['id'],'type':n['type']}
                if 'slot' in n: node['anchor']=spans[n['slot']]
                nodes.append(node)
            graph={'nodes':nodes,'edges':deepcopy(f['edges'])}; key=canonical(graph)
            outputs[key]=graph; derivations.append({'rule_id':rule['id'],'anchors':spans})
    return {'graphs':list(outputs.values()),'derivations':derivations,'complete':complete,'status':'unresolved' if not outputs else ('ambiguous' if len(outputs)>1 else ('complete' if complete else 'incomplete'))}


def induce(examples):
    """Enumerate anchored anti-unifications; select minimum cost per identical production."""
    candidates={}; log=[]
    for example in examples:
        try:
            f=_fragment(example); key=_stable(f)
            # Finite proposal class: one aligned fragment per example, equal templates anti-unify their hole contents.
            cost=sum(len(g.encode('utf8')) for g in f['gaps'])+len(f['nodes'])+3*len(f['edges'])
            if key not in candidates: candidates[key]={'fragment':f,'cost':cost,'origin':[],'observed_slots':[]}
            candidates[key]['origin'].append(example['id'])
            ordered=sorted((n for n in example['graph']['nodes'] if 'anchor' in n),key=lambda n:n['anchor'])
            candidates[key]['observed_slots'].append([example['text'][n['anchor'][0]:n['anchor'][1]] for n in ordered])
        except (ValueError,KeyError,TypeError) as e: log.append({'example':example.get('id'),'decision':'reject','reason':str(e)})
    ranked=sorted(candidates.values(),key=lambda c:(c['cost'],_stable(c['fragment'])))
    truncated=len(ranked)>MAX_TEMPLATES; ranked=ranked[:MAX_TEMPLATES]
    rules=[]
    for i,c in enumerate(ranked):
        observations=c.pop('observed_slots')
        # Only differing observed fillers justify an open hole; otherwise retain the observed surface.
        slots=[]
        for values in zip(*observations):
            distinct=sorted(set(values)); slots.append(None if len(distinct)>1 else distinct)
        rule={'id':'rule:%d'%i,**c,'slot_values':slots}; rules.append(rule)
        log.append({'decision':'candidate','rule_id':rule['id'],'cost':c['cost'],'origins':c['origin'],'derivation':'aligned spans; anchor contents abstracted as holes'})
    grammar={'version':'span-graph-grammar-v1','rules':rules,'bounds':{'nodes':MAX_NODES,'matches':MAX_MATCHES,'templates':MAX_TEMPLATES},'seed_knowledge':'none','candidate_search_complete':not truncated}
    proofs=[]
    for ex in examples:
        try:
            result=parse(ex['text'],grammar); target=canonical(ex['graph']); matched=any(canonical(g)==target for g in result['graphs'])
            proofs.append({'example':ex['id'],'derivable':matched,'complete':result['complete'],'status':result['status'],'derivations':result['derivations']})
        except (ValueError,KeyError,TypeError) as e: proofs.append({'example':ex.get('id'),'derivable':False,'reason':str(e)})
    return {'grammar':grammar,'candidates':log,'training_proofs':proofs,'search_scope':'minimum cost per equivalent template among enumerated aligned examples; no global optimality claim'}


def evaluate(grammar, examples):
    rows=[]
    for ex in examples:
        try:
            validate(ex); result=parse(ex['text'],grammar); target=canonical(ex['graph'])
            good=result['complete'] and len(result['graphs'])==1 and canonical(result['graphs'][0])==target
            rows.append({'id':ex['id'],'correct':good,'status':result['status'],'derivations':result['derivations']})
        except (ValueError,KeyError,TypeError) as e: rows.append({'id':ex.get('id'),'correct':False,'status':'invalid','reason':str(e)})
    return rows


def admit(learned, train, dev, baseline_correct=(), native_results=None):
    grammar=learned['grammar']; train_ids={e['id'] for e in train}; dev_ids={e['id'] for e in dev}
    reasons=[]
    if train_ids & dev_ids or {e['text'] for e in train} & {e['text'] for e in dev}: reasons.append('train/dev overlap')
    if not grammar['candidate_search_complete']: reasons.append('candidate search truncated')
    if not all(p.get('derivable') and p.get('complete') and p.get('status')=='complete' for p in learned['training_proofs']): reasons.append('training not uniquely derivable')
    rows=evaluate(grammar,dev); correct={r['id'] for r in rows if r['correct']}
    if correct != dev_ids: reasons.append('dev graph mismatch, ambiguity or incomplete search')
    if not set(baseline_correct)<=correct: reasons.append('previous correct dev regression')
    tags={tag for ex in dev for tag in ex.get('perturbations',[])}
    if not REQUIRED_PERTURBATIONS<=tags: reasons.append('missing perturbation coverage')
    # Fail closed until predicted graph-to-native provenance is independently verified.
    # Caller-provided booleans are not evidence of an execution or graph linkage.
    reasons.append('native execution and predicted-graph provenance linkage not implemented')
    return {'admitted':not reasons,'reasons':reasons,'dev':rows,'baseline_correct':sorted(baseline_correct),'seed_knowledge':grammar['seed_knowledge']}
