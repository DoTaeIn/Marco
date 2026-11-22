import copy
import importlib.util
from pathlib import Path
s=importlib.util.spec_from_file_location('acquire',Path(__file__).resolve().parents[1]/'acquire.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def ex(i,a,b,kind='passage'):
    text=a+' ~ '+b
    return {'id':i,'text':text,'kind':kind,'graph':{'nodes':[{'id':'x','type':'person','anchor':[0,len(a)]},{'id':'y','type':'object','anchor':[len(a)+3,len(text)]},{'id':'z','type':'event'}],'edges':[['z','agent','x'],['z','theme','y'],['z','polarity',{'literal':'positive'}]]}}

def test_fragment_reuses_holes_on_three_new_combinations_and_both_kinds():
    train=[ex('1','A','B'),ex('2','C','D','question')]
    learned=m.induce(train); assert len(learned['grammar']['rules'])==1
    for item in [ex('3','E','F'),ex('4','G','H','question'),ex('5','I','J')]:
        out=m.parse(item['text'],learned['grammar']); assert out['status']=='complete'; assert m.canonical(out['graphs'][0])==m.canonical(item['graph'])
    assert learned['grammar']['rules'][0]['origin']==['1','2']

def test_graph_equality_detects_extra_edge_and_ids_irrelevant():
    a=ex('a','A','B'); b=copy.deepcopy(a); b['graph']['edges'].append(['z','extra','x']); assert m.canonical(a['graph'])!=m.canonical(b['graph'])
    c=copy.deepcopy(a); c['graph']['nodes'][0]['id']='renamed'; c['graph']['edges'][0][2]='renamed'; assert m.canonical(a['graph'])==m.canonical(c['graph'])

def test_admission_requires_coverage_native_and_no_regression():
    train=[ex('t','A','B'),ex('t2','E','F')]; learned=m.induce(train); dev=[ex('d','C','D')]; dev[0]['perturbations']=['person','role','negation','source']
    assert not m.admit(learned,train,dev)['admitted']
    evidence={'d':dict.fromkeys(['complete','bindings','polarity','provenance','status'],True)}
    assert not m.admit(learned,train,dev,native_results=evidence)['admitted']
    assert not m.admit(learned,train,dev,baseline_correct=['absent'],native_results=evidence)['admitted']
    changed=copy.deepcopy(dev); changed[0]['graph']['edges'].append(['z','extra','x']); assert not m.admit(learned,train,changed,native_results=evidence)['admitted']

def test_ambiguity_and_answer_constant_rejected():
    x=ex('x','A','B'); x2=ex('x2','E','F'); y=ex('y','C','D'); y['graph']['edges'][0][1]='different'; y2=copy.deepcopy(y); y2['id']='y2'; y2['text']='G ~ H'; grammar=m.induce([x,x2,y,y2])['grammar']; assert m.parse('I ~ J',grammar)['status']=='ambiguous'
    z=ex('z','A','B'); z['graph']['edges'].append(['z','answer',{'literal':'A'}]); assert not m.induce([z])['training_proofs'][0]['derivable']

def test_unknown_text_and_limits():
    learned=m.induce([ex('x','A','B')]); assert m.parse('unrelated',learned['grammar'])['status']=='unresolved'
    assert not m._matches('aaaa',['','', ''],bound=1)[1]

def test_graph_meaning_changes_do_not_silently_pass():
    train=[ex('a','A','B'),ex('b','C','D')]; grammar=m.induce(train)['grammar']
    for category in ('role','negation','source'):
        case=ex(category,'E','F')
        if category=='role': case['graph']['edges'][0][2]='y'
        if category=='negation': case['graph']['edges'][2][2]={'literal':'negative'}
        if category=='source': case['graph']['edges'].append(['z','source','x'])
        assert not m.evaluate(grammar,[case])[0]['correct']

def test_single_filler_does_not_imply_unbounded_generalization():
    grammar=m.induce([ex('a','A','B')])['grammar']
    assert m.parse('C ~ D',grammar)['status']=='unresolved'
