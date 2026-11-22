import copy
from experiments.graph_example_acquisition import v2, native

def p(i,a,x,b,neg=False,scope=False):
    g1=' - ' if neg else ' + '; g2=' ! ' if scope else ' = '; text=a+g1+x+g2+b
    aa=[0,len(a)]; xx=[len(a)+len(g1),len(a)+len(g1)+len(x)]; bb=[len(text)-len(b),len(text)]
    graph={'nodes':[{'id':'a','type':'person','anchor':aa},{'id':'e','type':'event','anchor':xx},{'id':'b','type':'person','anchor':bb}], 'edges':[['e','actor','a'],['e','object','b'],['a','value',{'copy':aa}],['b','value',{'copy':bb}],['e','polarity',{'literal':'negative' if neg else 'positive'}],['e','scope',{'literal':'reported' if scope else 'direct'}]],'edge_spans':[[aa,xx],[xx,bb],[aa],[bb],[[aa[1],xx[0]]],[[xx[1],bb[0]]]],'project':[]}
    return {'id':i,'text':text,'kind':'passage','graph':graph}

def question(i,x,b):
    text='? '+x+' = '+b; xx=[2,2+len(x)]; bb=[len(text)-len(b),len(text)]; wh=[0,1]
    return {'id':i,'text':text,'kind':'question','graph':{'nodes':[{'id':'a','type':'person','anchor':wh},{'id':'e','type':'event','anchor':xx},{'id':'b','type':'person','anchor':bb}], 'edges':[['e','actor','a'],['e','object','b'],['b','value',{'copy':bb}],['e','polarity',{'literal':'positive'}],['e','scope',{'literal':'direct'}]],'edge_spans':[[wh,xx],[xx,bb],[bb],[[wh[1],xx[0]]],[[xx[1],bb[0]]]],'project':['a']}}

def test_patch_recombination_and_new_values():
    train=[]
    for neg,scope in [(False,False),(True,False),(False,True)]:
        train += [p(str(len(train)),'A','X','B',neg,scope),p(str(len(train)+1),'C','X','D',neg,scope)]
    learned=v2.induce(train); assert len(learned['grammar']['patches'])>=2
    for a,x,b in [('E','X','F'),('G','X','H'),('I','X','J')]:
        case=p('test',a,x,b,True,True); result=v2.parse(case['text'],learned['grammar'])
        assert result['status']=='complete'; assert v2.canonical(result['graphs'][0])==v2.canonical(case['graph'])
        assert any(len(d['patches'])==2 for d in result['derivations'])

def test_native_from_predicted_graphs_and_question_anchor_is_not_literal():
    ptrain=[p('p1','A','X','B'),p('p2','C','X','D')]; qtrain=[question('q1','X','B'),question('q2','X','D')]
    learned=v2.induce(ptrain+qtrain)
    pe=p('pt','E','X','F'); qe=question('qt','X','F')
    pg=v2.parse(pe['text'],learned['grammar']); qg=v2.parse(qe['text'],learned['grammar'])
    assert pg['status']==qg['status']=='complete'
    read,program=native.compile_pair(pg['graphs'][0],pe['text'],qg['graphs'][0],qe['text'])
    assert not any('body-node:' in term for triple in program['alternatives'][0]['patterns'] for term in triple)
    assert not any('?'==term for triple in program['alternatives'][0]['patterns'] for term in triple)
    result=native.run_pair(pg['graphs'][0],pe['text'],qg['graphs'][0],qe['text'],[['E']]); assert result['passed'],result

def test_absent_evidence_and_wrong_answer_rejected():
    a=p('p','A','X','B'); q=question('q','X','B'); assert not native.run_pair(a['graph'],a['text'],q['graph'],q['text'],[['B']])['passed']
    del a['graph']['edge_spans']; assert not native.run_pair(a['graph'],a['text'],q['graph'],q['text'],[['A']])['passed']

def test_admission_runs_predicted_pair_not_external_booleans():
    train=[p('p1','A','X','B'),p('p2','C','X','D'),question('q1','X','B'),question('q2','X','D')]
    learned=v2.induce(train); dev=[]; pairs=[]
    for i,tag in enumerate(('person','role','negation','source')):
        actor=chr(69+i); verb='X'; obj=chr(77+i)
        dev += [p('dp'+str(i),actor,verb,obj),question('dq'+str(i),verb,obj)]
        pairs.append({'id':'pair'+str(i),'passage_id':'dp'+str(i),'question_id':'dq'+str(i),'expected_bindings':[[actor]],'perturbations':[tag]})
    result=v2.admit(learned,train,dev,pairs); assert not result['admitted'] and all(x['passed'] for x in result['pairs']); assert 'missing mechanically verified independent contrast records' in result['reasons']
    bad=copy.deepcopy(pairs); bad[0]['expected_bindings']=[['wrong']]; assert not v2.admit(learned,train,dev,bad)['admitted']
    wrong=copy.deepcopy(dev); wrong[0]['graph']['edges'].append(['e','extra','a']); wrong[0]['graph']['edge_spans'].append([[0,1]]); assert not v2.admit(learned,train,wrong,pairs)['admitted']
    assert not v2.admit(learned,train,dev,[dict(pairs[0],perturbations=['person','role','negation','source'])])['admitted']


def test_native_negation_and_source_are_exact_graph_constraints():
    body=p('p','A','X','B',True,True); q=question('q','X','B')
    q['graph']['edges'][-2][2]={'literal':'negative'}; q['graph']['edges'][-1][2]={'literal':'reported'}
    assert native.run_pair(body['graph'],body['text'],q['graph'],q['text'],[['A']])['passed']
    q['graph']['edges'][-1][2]={'literal':'direct'}
    assert not native.run_pair(body['graph'],body['text'],q['graph'],q['text'],[['A']])['passed']

def test_input_copy_and_semantic_literal_are_disjoint():
    assert native.atom('copy','body-node:0') != 'body-node:0'
    assert native.atom('copy','x') != native.atom('literal','x')

def test_driver_end_to_end_synthetic(tmp_path, monkeypatch, capsys):
    import json, sys
    from experiments.graph_example_acquisition import driver
    train=[p('p1','A','X','B'),p('p2','C','X','D'),question('q1','X','B'),question('q2','X','D')]
    dev=[]; pairs=[]
    for i,tag in enumerate(('person','role','negation','source')):
        actor=chr(69+i); verb='X'; obj=chr(77+i)
        dev.extend([p('dp'+str(i),actor,verb,obj),question('dq'+str(i),verb,obj)])
        pairs.append({'id':str(i),'passage_id':'dp'+str(i),'question_id':'dq'+str(i),'expected_bindings':[[actor]],'perturbations':[tag]})
    trainpath=tmp_path/'train.json'; devpath=tmp_path/'dev.json'; out=tmp_path/'result.json'
    trainpath.write_text(json.dumps({'examples':train}),encoding='utf8'); devpath.write_text(json.dumps({'examples':dev,'pairs':pairs}),encoding='utf8')
    monkeypatch.setattr(sys,'argv',['driver','--train',str(trainpath),'--dev',str(devpath),'--output',str(out)])
    driver.main(); result=json.loads(out.read_text(encoding='utf8')); assert not result['admission']['admitted']; assert all(x['passed'] for x in result['admission']['pairs']); assert capsys.readouterr().out.strip()=='held'

def test_noncopy_predicate_and_question_anchors_remain_finite():
    a=p('a','A','X','B'); b=p('b','C','Y','D'); grammar=v2.induce([a,b])['grammar']
    assert v2.parse(p('x','E','X','F')['text'],grammar)['status']=='complete'
    assert v2.parse(p('y','E','Y','F')['text'],grammar)['status']=='complete'
    assert v2.parse(p('z','E','Z','F')['text'],grammar)['status']=='unresolved'
    q1=question('q1','X','B'); q2=question('q2','X','D'); q2['text']='#'+q2['text'][1:]
    g=v2.induce([q1,q2])['grammar']; assert v2.parse('! X = F',g)['status']=='unresolved'

def test_incremental_loop_admits_grounded_bundle_and_rejects_hallucination():
    train=[p('tp1','A','X','B'),p('tp2','C','X','D'),question('tq1','X','B'),question('tq2','X','D')]
    for ident,actor,obj in [('bad1','I','J'),('bad2','K','L')]:
        example=p(ident,actor,'X',obj); example['graph']['edges'].append(['e','extra','a']); example['graph']['edge_spans'].append([[0,1]]); train.append(example)
    dev=[]; pairs=[]
    for i,tag in enumerate(('person','role','negation','source')):
        actor=chr(69+i); obj=chr(77+i); dev.extend([p('dp'+str(i),actor,'X',obj),question('dq'+str(i),'X',obj)])
        pairs.append({'id':str(i),'passage_id':'dp'+str(i),'question_id':'dq'+str(i),'expected_bindings':[[actor]],'perturbations':[tag]})
    result=v2.acquire_incremental(train,dev,pairs); log=result['learning']['acquisition_log']
    assert any(x['decision']=='rejected' and x['reason'] in ('training ambiguity or graph mismatch','dev graph/native failure') for x in log)
    assert not result['admission']['admitted']  # adversarial extra-edge training examples remain unresolved

def test_missing_relevant_value_cannot_create_false_unique_answer():
    body=p('p','A','X','B'); q=question('q','X','B')
    # A distinct event has all query-matching relations, but its actor has no value.
    b=body['graph']; b['nodes'].extend([{'id':'unknown','type':'person','anchor':[0,1]},{'id':'event2','type':'event','anchor':[4,5]}])
    b['edges'] += [['event2','actor','unknown'],['event2','object','b'],['event2','polarity',{'literal':'positive'}],['event2','scope',{'literal':'direct'}]]
    b['edge_spans'] += [[[0,1],[4,5]],[[4,5],b['nodes'][2]['anchor']],[[1,4]],[[5,8]]]
    result=native.run_pair(b,body['text'],q['graph'],q['text'],[['A']])
    assert not result['passed']; assert 'missing or ambiguous copied value' in result['reason']

def test_actorless_relevant_context_holds_before_projection():
    body=p('p','A','X','B'); q=question('q','X','B'); graph=body['graph']
    graph['nodes'].append({'id':'event2','type':'event','anchor':[4,5]})
    graph['edges'] += [['event2','object','b'],['event2','polarity',{'literal':'positive'}],['event2','scope',{'literal':'direct'}]]
    graph['edge_spans'] += [[[4,5],graph['nodes'][2]['anchor']],[[1,4]],[[5,8]]]
    result=native.run_pair(graph,body['text'],q['graph'],q['text'],[['A']])
    assert not result['passed']; assert 'missing projected-role binding' in result['reason']

def test_distinct_nodes_with_identical_surface_hold():
    body=p('p','A','X','B'); q=question('q','X','B'); g=body['graph']
    g['nodes'] += [{'id':'a2','type':'person','anchor':[0,1]},{'id':'e2','type':'event','anchor':[4,5]}]
    g['edges'] += [['e2','actor','a2'],['e2','object','b'],['a2','value',{'copy':[0,1]}],['e2','polarity',{'literal':'positive'}],['e2','scope',{'literal':'direct'}]]
    g['edge_spans'] += [[[0,1],[4,5]],[[4,5],g['nodes'][2]['anchor']],[[0,1]],[[1,4]],[[5,8]]]
    result=native.run_pair(g,body['text'],q['graph'],q['text'],[['A']])
    assert not result['passed']; assert 'distinct structural referents' in result['reason']

def test_evidence_inside_fixed_gaps_is_learned_without_fabrication():
    train=[p('a','A','X','B'),p('b','C','X','D')]
    for ex in train:
        e=ex['graph']['edge_spans'][-2][0]; ex['graph']['edge_spans'][-2]=[[e[0]+1,e[1]-1]]
    target=p('dev','E','X','F'); e=target['graph']['edge_spans'][-2][0]; target['graph']['edge_spans'][-2]=[[e[0]+1,e[1]-1]]
    result=v2.parse(target['text'],v2.induce(train)['grammar'])
    assert result['status']=='complete'; assert v2.canonical(result['graphs'][0])==v2.canonical(target['graph'])

def test_full_utterance_evidence_with_unanchored_prefix_and_suffix():
    def wrapped(i,a,b):
        ex=p(i,a,'X',b); ex['text']='<<'+ex['text']+'>>'; g=ex['graph']
        def shift(span): return [span[0]+2,span[1]+2]
        for n in g['nodes']: n['anchor']=shift(n['anchor'])
        for edge in g['edges']:
            if isinstance(edge[2],dict) and 'copy' in edge[2]: edge[2]['copy']=shift(edge[2]['copy'])
        g['edge_spans']=[[shift(span) for span in spans] for spans in g['edge_spans']]
        g['edge_spans'][-1]=[[0,len(ex['text'])]]
        return ex
    train=[wrapped('a','A','B'),wrapped('b','C','D')]; target=wrapped('t','E','F')
    result=v2.parse(target['text'],v2.induce(train)['grammar'])
    assert result['status']=='complete'; assert v2.canonical(result['graphs'][0])==v2.canonical(target['graph'])

def test_independent_contrast_manifest_checks_actual_typed_graph_differences():
    examples=[p('base','A','X','B'),p('person','C','X','B'),p('role','B','X','A'),p('negative','A','X','B',True),p('source','A','X','B',False,True)]
    questions=[]
    for ex in examples:
        obj=ex['text'][-1]; q=question('q-'+ex['id'],'X',obj)
        q['graph']['edges'][-2][2]=copy.deepcopy(ex['graph']['edges'][-2][2]); q['graph']['edges'][-1][2]=copy.deepcopy(ex['graph']['edges'][-1][2]); questions.append(q)
    dev={x['id']:x for x in examples+questions}; predicted={x['id']:x['graph'] for x in examples+questions}
    pairs=[{'id':x['id'],'passage_id':x['id'],'question_id':'q-'+x['id'],'expected_bindings':[[x['text'][0]]]} for x in examples]; passing={x['id'] for x in examples}
    contrast=[{'category':'person','base_pair_id':'base','variant_pair_id':'person','predicate':'value'}, {'category':'role','base_pair_id':'base','variant_pair_id':'role','predicates':['actor','object']}, {'category':'negation','base_pair_id':'base','variant_pair_id':'negative','predicate':'polarity'}, {'category':'source','base_pair_id':'base','variant_pair_id':'source','predicate':'scope'}]
    categories,results=v2._check_contrasts(contrast,pairs,predicted,dev,passing)
    assert categories=={'person','role','negation','source'} and all(x['passed'] for x in results)
    forged=copy.deepcopy(contrast); forged[-1]['variant_pair_id']='person'; categories,_=v2._check_contrasts(forged,pairs,predicted,dev,passing)
    assert 'source' not in categories

def test_observed_edge_deletion_composes_with_independent_literal_patch():
    def event(i,a,b,neg=False,drop=False):
        ex=p(i,a,'X',b,neg,drop)
        if drop:
            ex['graph']['edges'].pop(); ex['graph']['edge_spans'].pop()
        return ex
    train=[]
    for neg,drop in [(False,False),(True,False),(False,True)]:
        train.extend([event('a'+str(len(train)),'A','B',neg,drop),event('b'+str(len(train)),'C','D',neg,drop)])
    learned=v2.induce(train); assert any(p.get('kind')=='remove' for p in learned['grammar']['patches'])
    for i,(a,b) in enumerate([('E','F'),('G','H'),('I','J')]):
        target=event('t'+str(i),a,b,True,True); parsed=v2.parse(target['text'],learned['grammar'])
        assert parsed['status']=='complete'; assert v2.canonical(parsed['graphs'][0])==v2.canonical(target['graph'])
        assert any(len(d['patches'])==2 for d in parsed['derivations'])

def test_real_native_contrast_admission_can_pass_without_tags_only():
    def make_question(body,ident):
        q=copy.deepcopy(body); q['id']=ident; q['kind']='question'; q['text']='?'+body['text'][1:]
        g=q['graph']; index=next(i for i,e in enumerate(g['edges']) if e[0]=='a' and e[1]=='value')
        g['edges'].pop(index); g['edge_spans'].pop(index); g['project']=['a']
        return q
    train=[]
    for neg,scope in [(False,False),(True,False),(False,True)]:
        for a,b in [('A','B'),('C','D')]:
            body=p('t'+str(len(train)),a,'X',b,neg,scope); train.append(body); train.append(make_question(body,'tq'+str(len(train))))
    cases=[('base','E','M',False,False),('person','F','M',False,False),('role','M','E',False,False),('negative','E','M',True,False),('source','E','M',False,True)]
    dev=[]; pairs=[]; question_ids={}
    for ident,a,b,neg,scope in cases:
        body=p('d-'+ident,a,'X',b,neg,scope); q=make_question(body,'q-'+ident); dev.append(body)
        if q['text'] not in question_ids: question_ids[q['text']]=q['id']; dev.append(q)
        pairs.append({'id':ident,'passage_id':body['id'],'question_id':question_ids[q['text']],'expected_bindings':[[a]],'perturbations':[{'person':'person','role':'role','negative':'negation','source':'source'}.get(ident,'person')]})
    contrasts=[{'category':'person','base_pair_id':'base','variant_pair_id':'person','predicate':'value'}, {'category':'role','base_pair_id':'base','variant_pair_id':'role','predicates':['actor','object']}, {'category':'negation','base_pair_id':'base','variant_pair_id':'negative','predicate':'polarity'}, {'category':'source','base_pair_id':'base','variant_pair_id':'source','predicate':'scope'}]
    result=v2.admit(v2.induce(train),train,dev,pairs,contrasts=contrasts)
    assert result['admitted'], result
    assert all(x['passed'] for x in result['contrasts'])
    assert not v2.admit(v2.induce(train),train,dev,pairs)['admitted']
    incremental=v2.acquire_incremental(train,dev,pairs,contrasts)
    assert incremental['admission']['admitted'], incremental['admission']
    assert any(entry['decision']=='accepted' for entry in incremental['learning']['acquisition_log'])

def test_edge_removal_never_turns_copy_hole_into_unbounded_noncopy_anchor():
    def sample(i,a,b,removed):
        ex=p(i,a,'X',b,removed,False)
        # Keep the semantic polarity constant; only the witnessed value edge differs.
        ex['graph']['edges'][-2][2]={'literal':'positive'}
        if removed:
            at=next(j for j,e in enumerate(ex['graph']['edges']) if e[0]=='a' and e[1]=='value')
            ex['graph']['edges'].pop(at); ex['graph']['edge_spans'].pop(at)
        return ex
    train=[sample('a','A','B',False),sample('b','C','D',False),sample('c','A','B',True),sample('d','C','D',True)]
    grammar=v2.induce(train)['grammar']; assert any(p.get('kind')=='remove' for p in grammar['patches'])
    assert v2.parse(sample('new','E','F',True)['text'],grammar)['status']=='unresolved'

def test_same_question_two_event_ablation_demonstrates_competing_answers():
    first=p('base','A','X','B'); first['text']+=' C'; g=first['graph']; c=[len(first['text'])-1,len(first['text'])]
    g['nodes'] += [{'id':'c','type':'person','anchor':c},{'id':'e2','type':'event','anchor':[4,5]}]
    g['edges'] += [['e2','actor','c'],['e2','object','b'],['c','value',{'copy':c}],['e2','polarity',{'literal':'negative'}],['e2','scope',{'literal':'direct'}]]
    g['edge_spans'] += [[c,[4,5]],[[4,5],[8,9]],[c],[[1,4]],[[5,8]]]
    second=copy.deepcopy(first); second['id']='alter'; second['text']+='!'
    for edge in second['graph']['edges']:
        if edge[1]=='polarity': edge[2]['literal']='negative' if edge[0]=='e' else 'positive'
    q=question('q','X','B')
    dev={'base':first,'alter':second,'q':q}; predicted={k:v['graph'] for k,v in dev.items()}
    pairs=[{'id':'base-pair','passage_id':'base','question_id':'q','expected_bindings':[['A']]},{'id':'alter-pair','passage_id':'alter','question_id':'q','expected_bindings':[['C']]}]
    assert native.run_pair(g,first['text'],q['graph'],q['text'],[['A']])['passed']
    assert native.run_pair(second['graph'],second['text'],q['graph'],q['text'],[['C']])['passed']
    record={'category':'negation','base_pair_id':'base-pair','altered_pair_id':'alter-pair','predicate':'polarity','query_predicates':['polarity']}
    categories,results=v2._check_contrasts([record],pairs,predicted,dev,{'base-pair','alter-pair'})
    assert categories=={'negation'},results
    assert all({tuple(x) for x in item['actual']}=={('A',),('C',)} for item in results[0]['constraint_ablation'])
    invalid=copy.deepcopy(record); invalid['query_predicates']=['scope']
    assert not v2._check_contrasts([invalid],pairs,predicted,dev,{'base-pair','alter-pair'})[0]

def test_proposal_bound_is_separate_from_parser_completion_and_configurable():
    train=[]
    for i,operator in enumerate('abcde'):
        for j,(a,b) in enumerate((('A','B'),('C','D'))):
            ex=p(f't{i}-{j}',a,'X',b); ex['text']=ex['text'].replace('+',operator); train.append(ex)
    train += [question('tq1','X','B'),question('tq2','X','D')]
    body=p('dp','E','X','F'); body['text']=body['text'].replace('+','e'); q=question('dq','X','F')
    pairs=[{'id':'pair','passage_id':'dp','question_id':'dq','expected_bindings':[['E']],'perturbations':['person']}]
    small=v2.acquire_incremental(train,[body,q],pairs,max_proposals=1)
    assert not small['learning']['search_complete']; assert small['learning']['grammar']['complete']
    assert 'candidate proposal search truncated; minimum unknown' in small['admission']['reasons']
    larger=v2.acquire_incremental(train,[body,q],pairs,max_proposals=100)
    assert any(e['decision']=='accepted' for e in larger['learning']['acquisition_log'])

def test_source_node_reference_follows_reporter_copy_value():
    ex=p('base','A','X','B'); ex['text']+=' C D'; g=ex['graph']; c=[len(ex['text'])-3,len(ex['text'])-2]; d=[len(ex['text'])-1,len(ex['text'])]
    g['nodes'] += [{'id':'claim1','type':'claim'},{'id':'claim2','type':'claim'},{'id':'c','type':'person','anchor':c},{'id':'d','type':'person','anchor':d}]
    g['edges'] += [['claim1','reporter','c'],['claim2','reporter','d'],['c','value',{'copy':c}],['d','value',{'copy':d}],['e','source','claim1']]
    g['edge_spans'] += [[c],[d],[c],[d],[c]]
    other=copy.deepcopy(g); other['edges'][-1][2]='claim2'
    assert v2._predicate_values(g,ex['text'],'source')!=v2._predicate_values(other,ex['text'],'source')

def test_learned_two_child_union_reuses_disjoint_fragments():
    children=[p('a','A','X','B'),p('b','C','X','D'),p('c','E','X','F'),p('d','G','X','H')]
    def combine(ident,a,b):
        sep=' ; '; text=a['text']+sep+b['text']
        return {'id':ident,'kind':'passage','text':text,'graph':v2._graph_union(a['graph'],b['graph'],len(a['text'])+len(sep))}
    train=children+[combine('ab',children[0],children[1]),combine('cd',children[2],children[3])]
    learned=v2.induce(train); assert learned['grammar']['unions']
    grammar=copy.deepcopy(learned['grammar']); used={u['left_rule'] for u in grammar['unions']}|{u['right_rule'] for u in grammar['unions']}
    grammar['rules']=[r for r in grammar['rules'] if r['id'] in used]
    assert all(len(r['fragment']['nodes'])==3 for r in grammar['rules'])
    for a,b in [(p('u','I','X','J'),p('v','K','X','L')),(p('u','M','X','N'),p('v','O','X','P'))]:
        case=combine('new',a,b); result=v2.parse(case['text'],grammar)
        assert result['status']=='complete',result
        assert v2.canonical(result['graphs'][0])==v2.canonical(case['graph'])
        assert any(d['rule'].startswith('union:') for d in result['derivations'])

def test_operator_substring_in_new_name_does_not_itself_forbid_name():
    grammar=v2.induce([p('a','A','X','B'),p('b','C','X','D')])['grammar']
    case=p('new','EXF','X','G'); result=v2.parse(case['text'],grammar)
    assert result['status']=='complete'; assert v2.canonical(result['graphs'][0])==v2.canonical(case['graph'])

def test_whole_child_clause_inside_copy_hole_is_not_accepted_as_name():
    grammar=v2.induce([p('a','A','X','B'),p('b','C','X','D')])['grammar']
    case=p('new','E + X = F','X','G'); result=v2.parse(case['text'],grammar)
    target=v2.canonical(case['graph'])
    assert not any(v2.canonical(graph)==target for graph in result['graphs'])
    assert result['invalid_conflicts']>0

def test_duplicate_parent_text_is_not_two_independent_union_observations():
    a=p('a','A','X','B'); b=p('b','C','X','D'); sep=' ; '
    parent={'id':'parent1','kind':'passage','text':a['text']+sep+b['text'],'graph':v2._graph_union(a['graph'],b['graph'],len(a['text'])+len(sep))}
    duplicate=copy.deepcopy(parent); duplicate['id']='parent2'
    assert not v2.induce([a,b,parent,duplicate])['grammar']['unions']

def test_union_induces_children_by_grammar_without_exact_child_training_text():
    children=[p('a','A','X','B'),p('b','C','X','D')]
    def combine(ident,a,b):
        sep=' ; '; return {'id':ident,'kind':'passage','text':a['text']+sep+b['text'],'graph':v2._graph_union(a['graph'],b['graph'],len(a['text'])+len(sep))}
    parents=[combine('p1',p('u','E','X','F'),p('v','G','X','H')),combine('p2',p('w','I','X','J'),p('x','K','X','L'))]
    assert all(child['text'] not in parent['text'] for child in children for parent in parents)
    grammar=v2.induce(children+parents)['grammar']; assert grammar['unions']
    needed={u['left_rule'] for u in grammar['unions']}|{u['right_rule'] for u in grammar['unions']}
    grammar['rules']=[r for r in grammar['rules'] if r['id'] in needed]
    target=combine('new',p('y','M','X','N'),p('z','O','X','P')); out=v2.parse(target['text'],grammar)
    assert out['status']=='complete'; assert v2.canonical(out['graphs'][0])==v2.canonical(target['graph'])

def test_incremental_bootstraps_union_with_missing_children_and_question(monkeypatch):
    def child(i,a,verb,b):
        result=p(i,a,verb,b)
        if verb=='X': result['graph']['edges'].append(['e','extra_kind',{'literal':'left'}]); result['graph']['edge_spans'].append([result['graph']['nodes'][1]['anchor']])
        return result
    children=[child('a','A','X','B'),child('b','C','X','D'),child('c','E','Y','F'),child('d','G','Y','H')]
    def combine(ident,a,b):
        sep=' ; '; return {'id':ident,'kind':'passage','text':a['text']+sep+b['text'],'graph':v2._graph_union(a['graph'],b['graph'],len(a['text'])+len(sep))}
    parents=[combine('p1',child('u','I','X','J'),child('v','K','Y','L')),combine('p2',child('w','M','X','N'),child('x','O','Y','P'))]
    train=children+parents+[question('q1','Y','F'),question('q2','Y','H')]
    generated=v2.induce(train); assert generated['grammar']['unions']
    generated['grammar']['rules']=[r for r in generated['grammar']['rules'] if len(r['fragment']['nodes'])==3]
    monkeypatch.setattr(v2,'induce',lambda _:copy.deepcopy(generated))
    body=combine('dev',child('z','Q','X','R'),child('zz','S','Y','T')); q=question('qdev','Y','T')
    pair={'id':'pair','passage_id':'dev','question_id':'qdev','expected_bindings':[['S']],'perturbations':['person']}
    result=v2.acquire_incremental(train,[body,q],[pair],max_proposals=1000)
    accepted=[entry for entry in result['learning']['acquisition_log'] if entry['decision']=='accepted']
    assert accepted, result['learning']['acquisition_log']
    assert any(any(c['kind']=='union' for c in entry['candidate']) and sum(c['kind']=='rule' for c in entry['candidate'])>=3 for entry in accepted)
