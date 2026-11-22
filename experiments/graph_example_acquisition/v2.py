"""Induce bounded span templates and reusable single-attribute graph patches."""
from copy import deepcopy
from itertools import product, permutations
import json
from . import native

MAX_RULES=128
MAX_PATCHES=64
MAX_MATCHES=256
MAX_APPLICATIONS=2
MAX_VARIANTS=256
MAX_UNIONS=64
MAX_UNION_COMPARISONS=10000

def key(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def _template(ex):
    g=ex['graph']; text=ex['text']; native._check(g,text)
    if ex['kind'] not in ('question','passage'): raise ValueError('invalid kind')
    nodes=g['nodes']; anchored=sorted((n for n in nodes if 'anchor' in n),key=lambda n:n['anchor'])
    if not anchored: raise ValueError('missing anchors')
    if any(a['anchor'][1]>b['anchor'][0] for a,b in zip(anchored,anchored[1:])): raise ValueError('overlapping anchors unsupported')
    rest=sorted((n for n in nodes if 'anchor' not in n),key=lambda n:(n['type'],n['id']))
    order=anchored+rest; rename={n['id']:'n%d'%i for i,n in enumerate(order)}
    spans=[n['anchor'] for n in anchored]; gaps=[]; last=0
    for a,b in spans: gaps.append(text[last:a]); last=b
    gaps.append(text[last:])
    def boundary(pos):
        for i,(a,b) in enumerate(spans):
            if pos==a: return ['start',i]
            if pos==b: return ['end',i]
        if pos==0: return ['text_start']
        if pos==len(text): return ['text_end']
        for i,(a,b) in enumerate(spans):
            if a<pos<b: return ['inside',i,pos-a]
        for i in range(len(spans)+1):
            start=0 if i==0 else spans[i-1][1]
            stop=len(text) if i==len(spans) else spans[i][0]
            if start<pos<stop: return ['gap',i,pos-start]
        raise ValueError('evidence/copy boundary is outside the text')
    def span_ref(s): return [boundary(s[0]),boundary(s[1])]
    def obj(o):
        if isinstance(o,str): return rename[o]
        if 'copy' in o: return {'copy_ref':span_ref(o['copy'])}
        return deepcopy(o)
    ns=[{'id':rename[n['id']],'type':n['type'],**({'slot':i} if 'anchor' in n else {})} for i,n in enumerate(order)]
    edges=[[rename[a],p,obj(b)] for a,p,b in g['edges']]
    evidence=[[span_ref(s) for s in ss] for ss in g['edge_spans']]
    return {'gaps':gaps,'nodes':ns,'edges':edges,'edge_spans':evidence,'project':[rename[i] for i in g['project']]},[text[a:b] for a,b in spans]


def _eligible_slots(fragment):
    # Only explicit typed input-copy nodes can generalize their text. Predicate,
    # WH and other anchors remain observed lexical evidence, never wildcards.
    eligible=set()
    for _,predicate,obj in fragment['edges']:
        if predicate=='value' and isinstance(obj,dict) and 'copy_ref' in obj:
            a,b=obj['copy_ref']
            if a[0]=='start' and b[0]=='end' and a[1]==b[1]: eligible.add(a[1])
    def all_refs(x):
        if isinstance(x,list):
            if len(x)==3 and x[0]=='inside' and isinstance(x[1],int): yield x[1]
            else:
                for y in x: yield from all_refs(y)
        elif isinstance(x,dict):
            for y in x.values(): yield from all_refs(y)
    eligible.difference_update(all_refs({'edges':fragment['edges'],'edge_spans':fragment['edge_spans']}))
    return eligible


def _slots(observations, fragment):
    eligible=_eligible_slots(fragment)
    result=[]
    for i,values in enumerate(zip(*observations)):
        distinct=sorted(set(values))
        result.append(None if i in eligible and len(distinct)>1 else distinct)
    return result


def induce(examples):
    groups={}; rejected=[]; typed_anchors={}
    for ex in examples:
        try:
            f,obs=_template(ex); k=key(f)
            copy_slots=_eligible_slots(f)
            for node in f['nodes']:
                if 'slot' in node and node['slot'] not in copy_slots:
                    typed_anchors.setdefault(node['type'],set()).add(obs[node['slot']])
            if k not in groups: groups[k]={'fragment':f,'origin':[],'observations':[]}
            groups[k]['origin'].append(ex['id']); groups[k]['observations'].append(obs)
        except (ValueError,KeyError,TypeError) as e: rejected.append({'example':ex.get('id'),'reason':str(e)})
    ordered=sorted(groups.values(),key=lambda r:(sum(len(x.encode()) for x in r['fragment']['gaps'])+len(r['fragment']['nodes'])+3*len(r['fragment']['edges']),key(r['fragment'])))
    complete=len(ordered)<=MAX_RULES; ordered=ordered[:MAX_RULES]; rules=[]
    for i,g in enumerate(ordered):
        f=g['fragment']; rules.append({'id':'r%d'%i,'fragment':f,'origins':g['origin'],'slots':_slots(g['observations'],f),'cost':sum(len(x.encode()) for x in f['gaps'])+len(f['nodes'])+3*len(f['edges'])})
    # Discover a typed graph patch only when one observed gap and one graph literal differ,
    # with all other graph structure and grounding identical. No semantic labels are preset.
    patches={}; patch_rejections=[]
    for a,b in product(rules,rules):
        if a is b: continue
        x,y=a['fragment'],b['fragment']
        if any(x[k]!=y[k] for k in ('nodes','edge_spans','project')):
            patch_rejections.append({'from':a['id'],'to':b['id'],'reason':'incompatible nodes, projection or evidence'}); continue
        gd=[i for i,(u,v) in enumerate(zip(x['gaps'],y['gaps'])) if u!=v]
        ed=[i for i,(u,v) in enumerate(zip(x['edges'],y['edges'])) if u!=v]
        if len(x['gaps'])!=len(y['gaps']) or len(x['edges'])!=len(y['edges']) or len(gd)!=1 or len(ed)!=1:
            patch_rejections.append({'from':a['id'],'to':b['id'],'reason':'not one gap and one edge difference'}); continue
        i=ed[0]; old,new=x['edges'][i],y['edges'][i]
        if old[:2]!=new[:2] or not isinstance(old[2],dict) or not isinstance(new[2],dict) or set(old[2])!={'literal'} or set(new[2])!={'literal'}:
            patch_rejections.append({'from':a['id'],'to':b['id'],'reason':'edge is not same-subject typed semantic literal change'}); continue
        patch={'gap_index':gd[0],'old_gap':x['gaps'][gd[0]],'new_gap':y['gaps'][gd[0]],'old_edge':old,'new_edge':new,'interface_nodes':x['nodes'],'edge_evidence':x['edge_spans'][i],'cost':len(y['gaps'][gd[0]].encode())+3,'origins':a['origins']+b['origins']}
        patches[key({k:v for k,v in patch.items() if k!='origins'})]=patch
    # Learn a one-edge insertion/deletion only from a pair with the same typed
    # interface and shared edge evidence, plus exactly one changed text gap.
    for a,b in product(rules,rules):
        if a is b: continue
        x,y=a['fragment'],b['fragment']
        if x['nodes']!=y['nodes'] or x['project']!=y['project'] or len(x['gaps'])!=len(y['gaps']): continue
        gd=[i for i,(u,v) in enumerate(zip(x['gaps'],y['gaps'])) if u!=v]
        if len(gd)!=1: continue
        xe={key([edge,spans]):[edge,spans] for edge,spans in zip(x['edges'],x['edge_spans'])}
        ye={key([edge,spans]):[edge,spans] for edge,spans in zip(y['edges'],y['edge_spans'])}
        removed=xe.keys()-ye.keys(); added=ye.keys()-xe.keys()
        if (len(removed),len(added)) not in ((1,0),(0,1)): continue
        direction='remove' if removed else 'add'
        change=xe[next(iter(removed))] if removed else ye[next(iter(added))]
        shared=[xe[k] for k in sorted(xe.keys()&ye.keys())]
        patch={'kind':direction,'gap_index':gd[0],'old_gap':x['gaps'][gd[0]],'new_gap':y['gaps'][gd[0]],'changed_edge':change[0],'changed_evidence':change[1],'required_edges':shared,'interface_nodes':x['nodes'],'cost':len(y['gaps'][gd[0]].encode())+3,'origins':a['origins']+b['origins']}
        patches[key({k:v for k,v in patch.items() if k!='origins'})]=patch
    patches=list(patches.values()); complete &= len(patches)<=MAX_PATCHES
    grammar={'version':'example-grammar-v2','rules':rules,'patches':patches[:MAX_PATCHES],'complete':True,'candidate_search_complete':complete,'typed_anchors':{k:sorted(v) for k,v in sorted(typed_anchors.items())},'unions':[],'bounds':{'rules':MAX_RULES,'patches':MAX_PATCHES,'matches':MAX_MATCHES,'patch_applications':MAX_APPLICATIONS,'variants_per_rule':MAX_VARIANTS,'unions':MAX_UNIONS,'union_comparisons':MAX_UNION_COMPARISONS},'seed':'none'}
    grammar['unions'],union_complete=_induce_unions(examples,grammar)
    grammar['candidate_search_complete'] &= union_complete
    proofs=[]
    for ex in examples:
        try:
            result=parse(ex['text'],grammar)
            target=canonical(ex['graph'])
            matches=[d for d in result['derivations'] if d['graph_key']==target]
            proofs.append({'id':ex['id'],'derivable':bool(matches),'complete':result['complete'],'status':result['status'],'minimum_derivation_cost':min((d['cost'] for d in matches),default=None),'derivations':result['derivations']})
        except (ValueError,KeyError,TypeError) as e: proofs.append({'id':ex.get('id'),'derivable':False,'reason':str(e)})
    return {'grammar':grammar,'training_proofs':proofs,'rejected':rejected,'rejected_patch_candidates':patch_rejections,'minimum':'minimum derivation cost among enumerated bounded rules and patch applications for each training graph; not a globally minimal grammar'}


def _shift_graph(graph,offset,prefix):
    rename={n['id']:prefix+n['id'] for n in graph['nodes']}
    def shift(span): return [span[0]+offset,span[1]+offset]
    nodes=[{'id':rename[n['id']],'type':n['type'],**({'anchor':shift(n['anchor'])} if 'anchor' in n else {})} for n in graph['nodes']]
    def obj(v):
        if isinstance(v,str): return rename[v]
        if 'copy' in v: return {'copy':shift(v['copy'])}
        return deepcopy(v)
    edges=[[rename[a],p,obj(b)] for a,p,b in graph['edges']]
    return {'nodes':nodes,'edges':edges,'edge_spans':[[shift(span) for span in spans] for spans in graph['edge_spans']],'project':[rename[x] for x in graph['project']]}


def _graph_union(left,right,right_offset):
    a=_shift_graph(left,0,'L:'); b=_shift_graph(right,right_offset,'R:')
    merged={k:a[k]+b[k] for k in ('nodes','edges','edge_spans','project')}
    if len(merged['nodes'])>8 or len(merged['project'])>2: raise ValueError('union exceeds native graph bounds')
    return merged


def _induce_unions(examples,grammar):
    # Child subspans are derived from the training grammar, not looked up as
    # complete raw training examples. Each parent is independently checked.
    inventory={}; comparisons=0; split_complete=True; parent_texts={e['id']:e['text'] for e in examples}
    def finish(complete):
        entries=[v for v in inventory.values() if len({parent_texts[i] for i in v['origins']})>=2]
        entries.sort(key=lambda x:(x['cost'],key(x)))
        return entries[:MAX_UNIONS],complete and len(entries)<=MAX_UNIONS
    for parent in examples:
        text=parent['text']; limit=min(len(text),257)
        if len(text)>257: split_complete=False
        prefixes=[]; suffixes=[]
        for split in range(1,limit):
            for side,part in (('left',text[:split]),('right',text[split:])):
                result=parse(part,grammar,allow_union=False)
                if result['status']!='complete': continue
                graph=result['graphs'][0]; graphkey=canonical(graph)
                proofs=[d for d in result['derivations'] if not d.get('patches') and d['graph_key']==graphkey]
                if proofs: (prefixes if side=='left' else suffixes).append((split,graph,[d['rule'] for d in proofs]))
        for (start,left,lids),(end,right,rids) in product(prefixes,suffixes):
            comparisons+=1
            if comparisons>MAX_UNION_COMPARISONS: return finish(False)
            if start>end: continue
            try:
                union=_graph_union(left,right,end)
                if canonical(union)!=canonical(parent['graph']): continue
                separator=text[start:end]
                for lid,rid in product(lids,rids):
                    k=key([lid,rid,separator]); entry=inventory.setdefault(k,{'left_rule':lid,'right_rule':rid,'separator':separator,'origins':[],'cost':len(separator.encode())+1})
                    entry['origins'].append(parent['id'])
            except (KeyError,ValueError,TypeError): continue
    return finish(split_complete)


def _parse_unions(text,grammar):
    graphs={}; derivations=[]; complete=True; conflict=False
    for union in grammar.get('unions',[]):
        separator=union['separator']; splits=0
        for i in range(1,len(text)):
            if not text.startswith(separator,i): continue
            right=i+len(separator)
            if right>=len(text): continue
            splits+=1
            if splits>256: complete=False; break
            left=parse(text[:i],grammar,allow_union=False); r=parse(text[right:],grammar,allow_union=False)
            complete &= left['complete'] and r['complete']; conflict |= left.get('span_conflict',False) or r.get('span_conflict',False)
            if left['status']!='complete' or r['status']!='complete': continue
            leftproof=[d for d in left['derivations'] if d.get('rule')==union['left_rule'] and d['graph_key']==canonical(left['graphs'][0])]
            rightproof=[d for d in r['derivations'] if d.get('rule')==union['right_rule'] and d['graph_key']==canonical(r['graphs'][0])]
            if not leftproof or not rightproof: continue
            try:
                graph=_graph_union(left['graphs'][0],r['graphs'][0],right); native._check(graph,text); k=canonical(graph); graphs[k]=graph
                derivations.append({'rule':'union:'+union['left_rule']+':'+union['right_rule'],'patches':[],'origins':union['origins'],'graph_key':k,'cost':union['cost']+min(x['cost'] for x in leftproof)+min(x['cost'] for x in rightproof),'children':[union['left_rule'],union['right_rule']]})
            except (KeyError,TypeError,ValueError): continue
    return list(graphs.values()),derivations,complete,conflict


def canonical(g):
    from itertools import permutations
    nodes=g['nodes']; ids=[n['id'] for n in nodes]
    if len(nodes)>8: raise ValueError('canonical graph node limit')
    labels=[{k:v for k,v in n.items() if k!='id'} for n in nodes]
    groups={}
    for i,label in enumerate(labels): groups.setdefault(key(label),[]).append(i)
    ordered=[groups[k] for k in sorted(groups)]
    best=None
    for choices in product(*(permutations(group) for group in ordered)):
        perm=[i for group in choices for i in group]
        rename={ids[old]:str(i) for i,old in enumerate(perm)}
        ns=[{k:v for k,v in nodes[old].items() if k!='id'} for old in perm]
        es=[]
        for edge,spans in zip(g['edges'],g['edge_spans']):
            a,p,b=edge; es.append([[rename[a],p,rename[b] if isinstance(b,str) else b],spans])
        value=key({'nodes':ns,'edges':sorted(es,key=key),'project':[rename[x] for x in g['project']]})
        if best is None or value<best: best=value
    return best


def _variants(rule, patches):
    queue=[(rule['fragment'],[])]; seen={key(rule['fragment'])}
    for depth in range(MAX_APPLICATIONS):
        new=[]
        for f,used in queue:
            if len(used)!=depth: continue
            for i,p in enumerate(patches):
                if i in used: continue
                index=p['gap_index']
                if index>=len(f['gaps']) or f['gaps'][index]!=p['old_gap'] or f['nodes']!=p['interface_nodes']: continue
                nf=deepcopy(f); nf['gaps'][index]=p['new_gap']; kind=p.get('kind','update')
                if kind=='update':
                    if p['old_edge'] not in f['edges'] or f['edge_spans'][f['edges'].index(p['old_edge'])]!=p['edge_evidence']: continue
                    nf['edges'][nf['edges'].index(p['old_edge'])]=p['new_edge']
                else:
                    available={key([edge,spans]) for edge,spans in zip(f['edges'],f['edge_spans'])}
                    if any(key(pair) not in available for pair in p['required_edges']): continue
                    edge=p['changed_edge']; evidence=p['changed_evidence']; pairkey=key([edge,evidence])
                    if kind=='add':
                        if edge in nf['edges']: continue
                        nf['edges'].append(edge); nf['edge_spans'].append(evidence)
                    elif kind=='remove':
                        if pairkey not in available: continue
                        position=nf['edges'].index(edge); nf['edges'].pop(position); nf['edge_spans'].pop(position)
                    else: continue
                # A patch must not turn an open copied-value hole into an
                # unconstrained predicate/other anchor or an unsafe interior span.
                if any(allowed is None and i not in _eligible_slots(nf) for i,allowed in enumerate(rule['slots'])): continue
                k=key(nf)
                if k not in seen:
                    if len(seen)>=MAX_VARIANTS: return queue+new,False
                    seen.add(k); new.append((nf,used+[i]))
        queue.extend(new)
    return queue,True


def _matches(text,gaps):
    if not text.startswith(gaps[0]): return [],True
    out=[]; complete=True
    def rec(i,start,spans):
        nonlocal complete
        if len(out)>=MAX_MATCHES: complete=False; return
        suffix=gaps[i+1]
        if i==len(gaps)-2:
            end=len(text)-len(suffix)
            if end>start and text[end:]==suffix: out.append(spans+[[start,end]])
            return
        for end in range(start+1,len(text)+1):
            if text.startswith(suffix,end): rec(i+1,end+len(suffix),spans+[[start,end]])
            if not complete:return
    rec(0,len(gaps[0]),[]); return out,complete


def parse(text,grammar,allow_union=True,allow_conflict_probe=True):
    graphs={}; derivations=[]; complete=grammar['complete']; span_conflict=False; invalid_conflicts=0; uncertain_conflicts=0; conflict_proofs=[]
    for rule in grammar['rules']:
        variants,variants_complete=_variants(rule,grammar['patches']); complete &= variants_complete
        for f,patches in variants:
            spans,done=_matches(text,f['gaps']); complete &= done
            for ss in spans:
                if any(allowed is not None and text[a:b] not in allowed for (a,b),allowed in zip(ss,rule['slots'])): continue
                slot_types={n['slot']:n['type'] for n in f['nodes'] if 'slot' in n}
                invalid=False
                if allow_conflict_probe:
                    for i,((a,b),allowed) in enumerate(zip(ss,rule['slots'])):
                        if allowed is not None: continue
                        lexical=any(typ!=slot_types[i] and any(surface and surface in text[a:b] for surface in observed) for typ,observed in grammar.get('typed_anchors',{}).items())
                        if not lexical: continue
                        child=parse(text[a:b],grammar,allow_union=False,allow_conflict_probe=False)
                        if child['status']=='complete':
                            child_graph=child['graphs'][0]; child_copies={edge[0] for edge in child_graph['edges'] if edge[1]=='value' and isinstance(edge[2],dict) and 'copy' in edge[2]}
                            has_operator=any(n['type']!=slot_types[i] and n['id'] not in child_copies and 'anchor' in n for n in child_graph['nodes'])
                            has_relation=any(edge[1]!='value' for edge in child_graph['edges'])
                            if has_operator and has_relation:
                                invalid=True; invalid_conflicts+=1
                                conflict_proofs.append({'copy_span':[a,b],'copy_type':slot_types[i],'child_derivations':child['derivations']})
                                break
                        uncertain_conflicts+=1
                if invalid: continue
                def boundary(ref):
                    if ref[0]=='text_start': return 0
                    if ref[0]=='text_end': return len(text)
                    if ref[0]=='start': return ss[ref[1]][0]
                    if ref[0]=='end': return ss[ref[1]][1]
                    if ref[0]=='inside':
                        a,b=ss[ref[1]]; value=a+ref[2]
                        if not a<value<b: raise ValueError('interior anchor offset is out of bounds')
                        return value
                    if ref[0]=='gap':
                        i=ref[1]; a=0 if i==0 else ss[i-1][1]; b=len(text) if i==len(ss) else ss[i][0]; value=a+ref[2]
                        if not a<value<b: raise ValueError('gap offset is out of bounds')
                        return value
                    raise ValueError('invalid span boundary')
                def sr(ref): return [boundary(ref[0]),boundary(ref[1])]
                try:
                    nodes=[{'id':n['id'],'type':n['type'],**({'anchor':ss[n['slot']]} if 'slot' in n else {})} for n in f['nodes']]
                    edges=[[a,p,{'copy':sr(b['copy_ref'])} if isinstance(b,dict) and 'copy_ref' in b else deepcopy(b)] for a,p,b in f['edges']]
                    graph={'nodes':nodes,'edges':edges,'edge_spans':[[sr(s) for s in ev] for ev in f['edge_spans']],'project':f['project']}
                    native._check(graph,text); graph_key=canonical(graph); graphs[graph_key]=graph
                    derivations.append({'rule':rule['id'],'patches':patches,'origins':rule['origins'],'graph_key':graph_key,'cost':rule['cost']+sum(grammar['patches'][i]['cost'] for i in patches)})
                except ValueError: pass
    if allow_union:
        union_graphs,union_derivations,union_complete,union_conflict=_parse_unions(text,grammar)
        complete &= union_complete; span_conflict |= union_conflict
        for graph in union_graphs: graphs[canonical(graph)]=graph
        derivations.extend(union_derivations)
    return {'graphs':list(graphs.values()),'complete':complete,'status':('hold' if not complete or (not graphs and (invalid_conflicts or uncertain_conflicts or span_conflict)) else 'unresolved' if not graphs else 'ambiguous' if len(graphs)>1 else 'complete'),'derivations':derivations,'span_conflict':span_conflict,'invalid_conflicts':invalid_conflicts,'uncertain_conflicts':uncertain_conflicts,'conflict_proofs':conflict_proofs}


def _resolved_value(graph,text,obj,visited=()):
    """Opaque structural value including referenced node children, with cycle guard."""
    if not isinstance(obj,str):
        if 'literal' in obj: return ('literal',obj['literal'])
        return ('copy',text[slice(*obj['copy'])])
    nodes={n['id']:n for n in graph['nodes']}; kind=nodes[obj]['type']
    if obj in visited: return ('cycle',kind)
    children=sorted([(p,_resolved_value(graph,text,target,visited+(obj,))) for subject,p,target in graph['edges'] if subject==obj],key=key)
    return ('node',kind,tuple(children))


def _predicate_values(graph,text,predicate):
    return sorted([_resolved_value(graph,text,obj) for _,p,obj in graph['edges'] if p==predicate],key=key)


def _predicate_context_values(graph,text,predicate):
    nodes={n['id']:n for n in graph['nodes']}; results=[]
    for subject,p,obj in graph['edges']:
        if p!=predicate: continue
        context=sorted([(other,_resolved_value(graph,text,target,(subject,))) for origin,other,target in graph['edges'] if origin==subject and other!=predicate],key=key)
        results.append((nodes[subject]['type'],context,_resolved_value(graph,text,obj,(subject,))))
    return sorted(results,key=key)


def _ablate_constraints(graph,predicates):
    if not isinstance(predicates,list) or not predicates or any(not isinstance(p,str) for p in predicates): raise ValueError('constraint predicates required')
    if len(set(predicates))!=len(predicates) or any(sum(edge[1]==name for edge in graph['edges'])!=1 for name in predicates): raise ValueError('each declared query constraint must identify exactly one edge')
    kept=[(e,spans) for e,spans in zip(graph['edges'],graph['edge_spans']) if e[1] not in predicates]
    if len(kept)==len(graph['edges']): raise ValueError('declared query constraint absent')
    # Prune only disconnected nodes, keeping the complete projected component.
    reachable=set(graph['project']); changed=True
    while changed:
        changed=False
        for (a,_,b),_ in kept:
            if isinstance(b,str) and (a in reachable or b in reachable):
                old=len(reachable); reachable.update((a,b)); changed |= len(reachable)!=old
    edges=[]; evidence=[]
    for edge,spans in kept:
        a,_,b=edge
        if a in reachable and (not isinstance(b,str) or b in reachable): edges.append(deepcopy(edge)); evidence.append(deepcopy(spans))
    return {'nodes':[deepcopy(n) for n in graph['nodes'] if n['id'] in reachable], 'edges':edges,'edge_spans':evidence,'project':list(graph['project'])}


def _check_contrasts(contrasts,pairs,predicted,devmap,passing):
    """Validate independent authored contrast declarations, never infer NL labels."""
    byid={p['id']:p for p in pairs}; successful=set(); results=[]
    for c in contrasts:
        try:
            cat=c['category']; base=c['base_pair_id']; other=c.get('altered_pair_id',c.get('variant_pair_id'))
            if cat not in ('person','role','negation','source') or base==other or base not in passing or other not in passing: raise ValueError('contrast needs two distinct passing pairs')
            p1=byid[base]; p2=byid[other]; id1=p1['passage_id']; id2=p2['passage_id']
            if id1==id2 or devmap[id1]['text']==devmap[id2]['text']: raise ValueError('contrast passages must differ')
            if {tuple(v) for v in p1['expected_bindings']}=={tuple(v) for v in p2['expected_bindings']}:
                if c.get('query_predicates') or cat in ('person','role'):
                    raise ValueError('contrast must change verified answer tuples')
            g1,g2=predicted[id1],predicted[id2]; t1,t2=devmap[id1]['text'],devmap[id2]['text']
            if cat=='role':
                ps=c['predicates']
                if not isinstance(ps,list) or len(ps)!=2 or ps[0]==ps[1]: raise ValueError('role contrast needs two predicates')
                a,b=(_predicate_values(g1,t1,p) for p in ps); x,y=(_predicate_values(g2,t2,p) for p in ps)
                if not a or not b or a==b or a!=y or b!=x: raise ValueError('declared role values do not swap')
            else:
                predicate=c['predicate']; a=_predicate_values(g1,t1,predicate); b=_predicate_values(g2,t2,predicate)
                required='copy' if cat=='person' else ('literal' if cat=='negation' else None)
                if not a or not b or (required and any(v[0]!=required for v in a+b)): raise ValueError('declared contrast does not change required typed values')
                if a==b and (cat=='person' or _predicate_context_values(g1,t1,predicate)==_predicate_context_values(g2,t2,predicate)): raise ValueError('declared graph predicate does not change')
            cross=[]; ablation=[]
            if c.get('query_predicates'):
                q1=p1['question_id']; q2=p2['question_id']
                if devmap[q1]['text']!=devmap[q2]['text'] or canonical(predicted[q1])!=canonical(predicted[q2]): raise ValueError('ablation contrast requires the same question graph and text')
                formal=_ablate_constraints(predicted[q1],c['query_predicates'])
                for passage,text_,expected in ((g1,t1,p1['expected_bindings']),(g2,t2,p2['expected_bindings'])):
                    probe=native.run_pair(passage,text_,formal,devmap[q1]['text'],[])
                    original={tuple(v) for v in expected}; obtained={tuple(v) for v in probe.get('actual',[])}
                    if probe.get('status')!='evidence' or not original<obtained or probe.get('provenance_gaps') or probe.get('ungrounded'):
                        raise ValueError('constraint ablation did not yield additional proven native binding')
                    ablation.append(probe)
                probes=[]
            elif cat in ('negation','source'):
                q1=p1['question_id']; q2=p2['question_id']
                cross=[native.check_cross_exclusion(g1,t1,predicted[q2],devmap[q2]['text']),native.check_cross_exclusion(g2,t2,predicted[q1],devmap[q1]['text'])]
                if not all(x['passed'] for x in cross): raise ValueError('crossed source/polarity counterfactual has evidence or incomplete search')
                # A failed cross-query alone can be caused by an unrelated edit.
                # Replace only the tested semantic literal in the formal query and
                # require native evidence to return with the verified answer.
                if len(a)!=1 or len(b)!=1: raise ValueError('counterfactual requires one literal per side')
                def probe(query,old,new,body,bodytext,qtext,expected):
                    formal=deepcopy(query)
                    edges=[e for e in formal['edges'] if e[1]==predicate and e[2]=={'literal':old}]
                    if len(edges)!=1: raise ValueError('question lacks a unique tested literal')
                    edges[0][2]={'literal':new}
                    return native.run_pair(body,bodytext,formal,qtext,expected)
                probes=[probe(predicted[q2],b[0][1],a[0][1],g1,t1,devmap[q2]['text'],p1['expected_bindings']),probe(predicted[q1],a[0][1],b[0][1],g2,t2,devmap[q1]['text'],p2['expected_bindings'])]
                if not all(x['passed'] for x in probes): raise ValueError('literal-only formal probe did not restore expected native evidence')
            else: probes=[]
            successful.add(cat); results.append({'category':cat,'base_pair_id':base,'variant_pair_id':other,'passed':True,'cross_exclusion':cross,'literal_only_probes':probes,'constraint_ablation':ablation})
        except (KeyError,TypeError,ValueError) as e: results.append({'category':c.get('category'),'passed':False,'reason':str(e)})
    return successful,results


def admit(learned, train, dev, pairs, baseline_correct=(), contrasts=()):
    """Reparse each held-out text, verify whole graphs, then execute predicted pairs."""
    reasons=[]; grammar=learned['grammar']; train_ids={x['id'] for x in train}; devmap={x['id']:x for x in dev}
    if len(devmap)!=len(dev) or len(train_ids)!=len(train): reasons.append('duplicate example IDs')
    if train_ids & set(devmap) or {x['text'] for x in train}&{x['text'] for x in dev}: reasons.append('train/dev overlap')
    if not grammar['complete']: reasons.append('grammar parse bounds incomplete')
    if learned.get('search_complete') is False or grammar.get('candidate_search_complete') is False: reasons.append('candidate proposal search truncated; minimum unknown')
    if not learned['training_proofs'] or any(not x.get('derivable') or not x.get('complete') or x.get('status')!='complete' for x in learned['training_proofs']): reasons.append('training graph not uniquely derived')
    predicted={}; outcomes=[]
    for ex in dev:
        try:
            native._check(ex['graph'],ex['text']); result=parse(ex['text'],grammar)
            good=result['status']=='complete' and canonical(result['graphs'][0])==canonical(ex['graph'])
            if good: predicted[ex['id']]=result['graphs'][0]
            outcomes.append({'id':ex['id'],'correct':good,'status':result['status'],'derivations':result['derivations']})
        except (KeyError,ValueError,TypeError) as exc: outcomes.append({'id':ex.get('id'),'correct':False,'status':'invalid','reason':str(exc)})
    goodids={r['id'] for r in outcomes if r['correct']}
    if goodids!=set(devmap): reasons.append('held-out full graph mismatch or ambiguity')
    if not set(baseline_correct)<=goodids: reasons.append('prior dev regression')
    checks=[]; tags=set(); pairids=set(); covered=set()
    for pair in pairs:
        try:
            pid=pair['id']; pi=pair['passage_id']; qi=pair['question_id']
            if pid in pairids: raise ValueError('duplicate pair ID')
            pairids.add(pid)
            if pi not in predicted or qi not in predicted: raise ValueError('pair lacks unique correct predicted graphs')
            if devmap[pi]['kind']!='passage' or devmap[qi]['kind']!='question': raise ValueError('pair kinds invalid')
            result=native.run_pair(predicted[pi],devmap[pi]['text'],predicted[qi],devmap[qi]['text'],pair['expected_bindings'])
            if result['passed']:
                tags.update(pair.get('perturbations',[])); covered.update((pi,qi))
            checks.append({'id':pid,**result})
        except (ValueError,KeyError,TypeError) as e: checks.append({'id':pair.get('id'),'passed':False,'reason':str(e)})
    if not checks or any(not x['passed'] for x in checks): reasons.append('native pair check failed or absent')
    if covered!=set(devmap): reasons.append('not all dev graphs covered by passing native pairs')
    required=('person','role','negation','source')
    passing_ids={x['id'] for x in checks if x['passed']}
    covered_pairs=[p for p in pairs if p.get('id') in passing_ids]
    if not any(all(tag in pair.get('perturbations',[]) for tag,pair in zip(required,choice)) for choice in permutations(covered_pairs,4)):
        reasons.append('missing distinct passing perturbation pairs')
    categories,contrast_results=_check_contrasts(contrasts,pairs,predicted,devmap,passing_ids)
    if categories!=set(required): reasons.append('missing mechanically verified independent contrast records')
    return {'admitted':not reasons,'reasons':reasons,'dev':outcomes,'pairs':checks,'contrasts':contrast_results,'seed':'none'}


MAX_LOOP_PROPOSALS=512
MAX_LOOP_ROUNDS=32

def _dev_state(grammar, dev, pairs):
    """Dev input checks a candidate; it never generates a candidate."""
    records={}; failures=[]; correct=set()
    for ex in dev:
        try:
            native._check(ex['graph'],ex['text']); r=parse(ex['text'],grammar)
            if r['status']=='unresolved': continue
            if r['status']!='complete':
                failures.append({'example':ex['id'],'reason':r['status']}); continue
            if canonical(r['graphs'][0])!=canonical(ex['graph']):
                failures.append({'example':ex['id'],'reason':'full graph mismatch'}); continue
            records[ex['id']]=(ex,r['graphs'][0]); correct.add(ex['id'])
        except (TypeError,ValueError,KeyError) as e: failures.append({'example':ex.get('id'),'reason':str(e)})
    passed=set(); pair_results=[]
    for pair in pairs:
        pi=pair.get('passage_id'); qi=pair.get('question_id')
        if pi not in records or qi not in records: continue
        pe,pg=records[pi]; qe,qg=records[qi]
        if pe['kind']!='passage' or qe['kind']!='question':
            failures.append({'pair':pair.get('id'),'reason':'pair kinds'}); continue
        r=native.run_pair(pg,pe['text'],qg,qe['text'],pair['expected_bindings'])
        pair_results.append({'id':pair['id'],**r})
        if not r['passed']: failures.append({'pair':pair['id'],'reason':r.get('reason','native mismatch')})
        else: passed.add(pair['id'])
    return {'correct':correct,'pairs':passed,'failures':failures,'pair_results':pair_results}


def acquire_incremental(train,dev,pairs,contrasts=(),max_proposals=MAX_LOOP_PROPOSALS,max_rounds=MAX_LOOP_ROUNDS):
    """Greedy, bounded candidate bundles, each admitted by predicted dev/native checks.

    Candidates are generated exclusively by training examples. Ordinary bundles
    contain at most two productions. A union dependency closure can additionally
    include its missing child rules and one other rule. This is not a global minimum
    search or held-out evaluation.
    """
    if type(max_proposals) is not int or max_proposals<1 or type(max_rounds) is not int or max_rounds<1: raise ValueError('positive search bounds required')
    generated=induce(train); pool=generated['grammar']; log=[]
    empty={'version':pool['version'],'rules':[],'patches':[],'complete':True,'candidate_search_complete':pool['candidate_search_complete'],'typed_anchors':pool['typed_anchors'],'unions':[],'bounds':pool['bounds'],'seed':'none'}
    current=empty; prior=_dev_state(current,dev,pairs); prior_train=set()
    remaining=[('rule',r) for r in pool['rules']]+[('patch',p) for p in pool['patches']]+[('union',u) for u in pool['unions']]
    rounds=0; truncated=False
    while remaining and rounds<max_rounds:
        rounds+=1; proposal_set=set()
        for i in range(len(remaining)):
            proposal_set.add((i,))
            for j in range(i+1,len(remaining)): proposal_set.add((i,j))
        # Bootstrap a union together with missing child rules and optionally one
        # additional rule, such as the question side of a native pair.
        present={r['id'] for r in current['rules']}
        remaining_rules={record['id']:i for i,(kind,record) in enumerate(remaining) if kind=='rule'}
        for i,(kind,entry) in enumerate(remaining):
            if kind!='union': continue
            required={entry['left_rule'],entry['right_rule']}-present
            if not required<=set(remaining_rules): continue
            closure={i}|{remaining_rules[r] for r in required}
            proposal_set.add(tuple(sorted(closure)))
            for j,(other_kind,_) in enumerate(remaining):
                if other_kind=='rule' and j not in closure: proposal_set.add(tuple(sorted(closure|{j})))
        proposals=sorted(proposal_set,key=lambda indices:(sum(remaining[i][1]['cost'] for i in indices),indices))
        overflow=len(proposals)>max_proposals
        if overflow: proposals=proposals[:max_proposals]
        accepted=None
        for indices in proposals:
            candidate=deepcopy(current); members=[remaining[i] for i in indices]
            for kind,record in members: candidate[{'rule':'rules','patch':'patches','union':'unions'}[kind]].append(record)
            derivable=set(); proofs=[]; train_failures=[]
            for ex in train:
                try:
                    parsed=parse(ex['text'],candidate); target=canonical(ex['graph'])
                    matched=[d for d in parsed['derivations'] if d['graph_key']==target]
                    if parsed['status']=='unresolved': continue
                    if parsed['status']!='complete' or not matched:
                        train_failures.append({'id':ex['id'],'status':parsed['status'],'reason':'training ambiguity or graph mismatch'}); continue
                    derivable.add(ex['id']); proofs.append({'id':ex['id'],'minimum_cost':min(d['cost'] for d in matched)})
                except (ValueError,KeyError,TypeError): pass
            novel=derivable-prior_train
            label=[{'kind':kind,'origins':entry['origins'],'cost':entry['cost']} for kind,entry in members]
            if train_failures:
                log.append({'decision':'rejected','candidate':label,'reason':'training ambiguity or graph mismatch','failures':train_failures}); continue
            if not novel:
                log.append({'decision':'rejected','candidate':label,'reason':'no new train derivation'}); continue
            state=_dev_state(candidate,dev,pairs)
            if state['failures']:
                log.append({'decision':'rejected','candidate':label,'reason':'dev graph/native failure','failures':state['failures']}); continue
            if not prior['correct']<=state['correct'] or not prior['pairs']<=state['pairs']:
                log.append({'decision':'rejected','candidate':label,'reason':'previously correct dev regression'}); continue
            if not state['pairs']-prior['pairs']:
                log.append({'decision':'rejected','candidate':label,'reason':'no newly passing native dev pair'}); continue
            accepted=(indices,candidate,state,derivable)
            log.append({'decision':'accepted','candidate':label,'new_train_ids':sorted(novel),'new_native_pairs':sorted(state['pairs']-prior['pairs']),'training_proofs':proofs,'native_proofs':state['pair_results']}); break
        if accepted is None:
            if overflow: truncated=True
            break
        indices,current,prior,prior_train=accepted
        remaining=[entry for i,entry in enumerate(remaining) if i not in indices]
    if rounds>=max_rounds and remaining: truncated=True
    proofs=[]
    for ex in train:
        try:
            r=parse(ex['text'],current); target=canonical(ex['graph']); matched=[d for d in r['derivations'] if d['graph_key']==target]
            proofs.append({'id':ex['id'],'derivable':bool(matched),'complete':r['complete'],'status':r['status'],'minimum_derivation_cost':min((d['cost'] for d in matched),default=None),'derivations':r['derivations']})
        except (ValueError,KeyError,TypeError) as e: proofs.append({'id':ex.get('id'),'derivable':False,'reason':str(e)})
    # Candidate search completeness is separate from completeness of parsing
    # using the actually accepted inventory.
    search_complete=not truncated and pool['candidate_search_complete']
    learned={'grammar':current,'training_proofs':proofs,'candidate_rejections':generated['rejected']+generated['rejected_patch_candidates'],'acquisition_log':log,'search_truncated':not search_complete,'search_complete':search_complete,'proposal_bound':max_proposals,'round_bound':max_rounds,'minimum':'greedy lowest-cost accepted bundle within bounded proposals; not a global optimum'}
    return {'learning':learned,'admission':admit(learned,train,dev,pairs,contrasts=contrasts)}
