"""Mechanical v2 graph transport to the existing native query executor."""
import json
from experiments.graph_language_repair.questions.query_graph import execute_query_graph


def atom(kind, value):
    return kind+':'+json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode().hex()


def _span(text, s):
    return isinstance(s,list) and len(s)==2 and all(type(v) is int for v in s) and 0<=s[0]<s[1]<=len(text)


def _check(graph,text):
    if set(graph)!={'nodes','edges','edge_spans','project'}: raise ValueError('unsupported graph fields')
    nodes=graph['nodes']; edges=graph['edges']; ids=[n['id'] for n in nodes]
    if any(set(n)-{'id','type','anchor'} or not isinstance(n.get('type'),str) or not isinstance(n.get('id'),str) for n in nodes): raise ValueError('invalid node')
    if len({json.dumps(e,ensure_ascii=False,sort_keys=True) for e in edges})!=len(edges): raise ValueError('duplicate graph edge')
    if len(ids)!=len(set(ids)): raise ValueError('duplicate nodes')
    evidence=graph.get('edge_spans')
    if not isinstance(evidence,list) or len(evidence)!=len(edges): raise ValueError('missing edge evidence')
    for spans in evidence:
        if not spans or any(not _span(text,s) for s in spans): raise ValueError('missing or invalid edge evidence')
    for n in nodes:
        if 'anchor' in n and not _span(text,n['anchor']): raise ValueError('invalid node anchor')
    for a,p,b in edges:
        if a not in ids or not isinstance(p,str): raise ValueError('invalid edge')
        if p=='value' and (not isinstance(b,dict) or set(b)!={'copy'}): raise ValueError('value edges require typed input copies')
        if isinstance(b,str):
            if b not in ids: raise ValueError('invalid node reference')
        elif isinstance(b,dict) and set(b)=={'copy'}:
            if not _span(text,b['copy']): raise ValueError('invalid copy span')
            if text[slice(*b['copy'])].startswith('?'): raise ValueError('copy conflicts with native variable')
        elif not isinstance(b,dict) or set(b)!={'literal'} or not isinstance(b['literal'],str): raise ValueError('invalid typed object')
    if any(x not in ids for x in graph['project']) or len(graph['project'])>2 or len(set(graph['project']))!=len(graph['project']): raise ValueError('invalid projection')


def _obj(value,text,lookup):
    if isinstance(value,str): return lookup[value]
    if 'literal' in value: return atom('literal',value['literal'])
    return atom('copy', text[slice(*value['copy'])])


def compile_pair(pgraph,ptext,qgraph,qtext):
    _check(pgraph,ptext); _check(qgraph,qtext)
    if pgraph['project'] or not qgraph['project']: raise ValueError('missing or invalid question projection')
    ids={n['id']:'body-node:%d'%i for i,n in enumerate(pgraph['nodes'])}
    qids={n['id']:'?q%d'%i for i,n in enumerate(qgraph['nodes'])}
    rows=[]
    def add(t,spans,derived=False):
        rows.append({'id':'evidence:%d'%len(rows),'triple':t,'polarity':True,'modality':'asserted','claim':'claim:0','scope_kind':'direct_text','layer':'meta' if derived else 'content','spans':spans,'depends_on':[],'reading':'reading:0','hypotheses':[],'construction':None,'proof':None})
    for n in pgraph['nodes']:
        spans=[]
        if 'anchor' in n: spans.append(n['anchor'])
        for edge,ss in zip(pgraph['edges'],pgraph['edge_spans']):
            if edge[0]==n['id'] or edge[2]==n['id']:
                spans += [s for s in ss if s not in spans]
        if not spans: raise ValueError('node type lacks authored support')
        add([ids[n['id']],'node_type',atom('type',n['type'])],spans,True)
    for e,spans in zip(pgraph['edges'],pgraph['edge_spans']):
        a,p,b=e; add([ids[a],atom('predicate',p),_obj(b,ptext,ids)],spans)
    patterns=[[qids[n['id']],'node_type',atom('type',n['type'])] for n in qgraph['nodes']]
    patterns += [[qids[a],atom('predicate',p),_obj(b,qtext,qids)] for a,p,b in qgraph['edges']]
    project=[]
    for i,node in enumerate(qgraph['project']):
        out='?answer%d'%i; project.append(out); patterns.append([qids[node],atom('predicate','value'),out])
    if len(patterns)>32: raise ValueError('native pattern limit')
    graph={'schema':'graph-language-repair-reading-v1','text':ptext,'rows':rows,'limits':{'complete':True}}
    program={'version':'query-graph-v1','alternatives':[{'id':'induced','patterns':patterns,'project':project}]}
    return graph,program


def run_pair(pgraph,ptext,qgraph,qtext,expected):
    try:
        reading,program=compile_pair(pgraph,ptext,qgraph,qtext)
        # First search the structural query without projected surface-value rows.
        # Otherwise a relevant node lacking a value silently disappears and can make
        # a different answer look unique. The pre-query preserves joint bindings.
        qids={n['id']:'?q%d'%i for i,n in enumerate(qgraph['nodes'])}
        projected_nodes=[qids[n] for n in qgraph['project']]
        count=len(projected_nodes)
        structural_patterns=program['alternatives'][0]['patterns'][:-count]
        def variables(patterns): return {v for p in patterns for v in p if v.startswith('?')}
        incident=[p for p in structural_patterns if any(v in projected_nodes for v in p)]
        core=[p for p in structural_patterns if p not in incident]
        frontier=sorted(variables(core)&variables(incident))
        if not core or not frontier or len(frontier)>2:
            return {'passed':False,'reason':'unsupported structural candidate frontier'}
        core_program={'version':'query-graph-v1','alternatives':[{'id':'candidate_context','patterns':core,'project':frontier}]}
        context=execute_query_graph(reading,core_program)
        if context.get('status')!='evidence': return {'passed':False,'reason':'candidate-context search incomplete or no evidence','status':context.get('status')}
        for context_match in context['alternatives'][0]['matches']:
            if context_match.get('provenance_gaps'): return {'passed':False,'reason':'candidate-context provenance incomplete'}
            bindings=context_match['bindings']
            witness_patterns=[[bindings.get(term,term) for term in pattern] for pattern in incident]
            witness={'version':'query-graph-v1','alternatives':[{'id':'role_witness','patterns':witness_patterns,'project':projected_nodes}]}
            witness_result=execute_query_graph(reading,witness)
            if witness_result.get('status')=='no_evidence':
                return {'passed':False,'reason':'relevant context has missing projected-role binding'}
            if witness_result.get('status')!='evidence':
                return {'passed':False,'reason':'projected-role witness incomplete','status':witness_result.get('status')}
            if any(m.get('provenance_gaps') for m in witness_result['alternatives'][0]['matches']):
                return {'passed':False,'reason':'projected-role witness provenance incomplete'}
        pre={'version':'query-graph-v1','alternatives':[{'id':'structural_precheck','patterns':structural_patterns, 'project':projected_nodes}]}
        structural=execute_query_graph(reading,pre)
        if structural.get('status')!='evidence': return {'passed':False,'reason':'structural candidate search incomplete or no evidence','status':structural.get('status'),'detail':structural.get('reason')}
        structural_matches=structural['alternatives'][0]['matches']
        structural_gaps=[g for m in structural_matches for g in m.get('provenance_gaps',[])]
        if structural_gaps: return {'passed':False,'reason':'structural provenance incomplete','provenance_gaps':structural_gaps}
        expected_encoded=set(); referents_by_surface={}
        for match in structural_matches:
            values=[]
            for var in projected_nodes:
                node=match['bindings'][var]
                copies={r['triple'][2] for r in reading['rows'] if r['triple'][0]==node and r['triple'][1]==atom('predicate','value') and r['triple'][2].startswith('copy:')}
                if len(copies)!=1: return {'passed':False,'reason':'relevant structural candidate has missing or ambiguous copied value'}
                values.append(next(iter(copies)))
            value_tuple=tuple(values)
            referent_tuple=tuple(match['bindings'][var] for var in projected_nodes)
            referents_by_surface.setdefault(value_tuple,set()).add(referent_tuple)
            expected_encoded.add(value_tuple)
        if any(len(referents)>1 for referents in referents_by_surface.values()):
            return {'passed':False,'reason':'distinct structural referents share a copied value tuple'}
        result=execute_query_graph(reading,program)
        if result.get('status')!='evidence': return {'passed':False,'reason':'native search incomplete or no evidence','status':result.get('status'),'detail':result.get('reason')}
        alt=result['alternatives'][0]; matches=alt['matches']; projection=program['alternatives'][0]['project']
        encoded={tuple(m['bindings'][v] for v in projection) for m in matches}
        if encoded!=expected_encoded: return {'passed':False,'reason':'surface projection lost a structural candidate'}
        def decode(value):
            if not value.startswith('copy:'): raise ValueError('projected value is not a typed input copy')
            result=json.loads(bytes.fromhex(value[5:]).decode('utf8'))
            if not isinstance(result,str): raise ValueError('invalid copied value')
            return result
        actual=sorted(set(tuple(decode(m['bindings'][v]) for v in projection) for m in matches))
        expected=sorted(set(tuple(x) for x in expected))
        gaps=[g for m in matches for g in m.get('provenance_gaps',[])]
        ungrounded=any(not ref.get('spans') for m in matches for ref in m.get('source_refs',[]))
        proof_refs=[{'bindings':{v:decode(m['bindings'][v]) for v in projection},'sources':[{'rows':ref.get('rows',[]),'spans':ref.get('spans',[]),'claims':ref.get('claims',[]),'scope_kinds':ref.get('scope_kinds',[])} for ref in m.get('source_refs',[])]} for m in matches]
        return {'passed':actual==expected and not gaps and not ungrounded,'actual':[list(t) for t in actual],'provenance_gaps':gaps,'ungrounded':ungrounded,'status':result['status'],'proof_refs':proof_refs}
    except (KeyError,TypeError,ValueError) as exc:
        return {'passed':False,'reason':str(exc)}


def check_cross_exclusion(pgraph,ptext,qgraph,qtext):
    """Check a held-out counterfactual query yields complete no-evidence, not negation."""
    try:
        reading,program=compile_pair(pgraph,ptext,qgraph,qtext)
        result=execute_query_graph(reading,program)
        return {'passed':result.get('status')=='no_evidence','status':result.get('status'),'reason':result.get('reason')}
    except (ValueError,TypeError,KeyError) as exc:
        return {'passed':False,'reason':str(exc)}
