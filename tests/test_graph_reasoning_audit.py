import copy
import hashlib
import unittest
from unittest import mock
from tools import graph_reasoning_audit as audit


def program():
    return {'schema': 'marco-graph-vm-program-v1', 'entry': 'value', 'nodes': [
        {'id':'value','op':'set','name':'v','value':{'input':['number']},'next':'check'},
        {'id':'check','op':'branch','left':{'var':['v']},'right':{'literal':17},'yes':'yes','no':'no'},
        {'id':'yes','op':'return','value':{'literal':{'matched':True}}},
        {'id':'no','op':'return','value':{'literal':{'matched':False}}}]}


def frame():
    text='Public structured source: edge origin.'
    return {'schema':'marco-graph-frame-v1',
            'nodes':[{'id':x,'type':'type:fixture','scope':'scope:fixture','value':x} for x in ['node:qa','node:qb']],
            'edges':[{'id':'edge:qa','source':'node:qa','relation':'relation:origin','target':'node:qb','scope':'scope:chosen','evidence':['span:qa']},
                     {'id':'edge:qb','source':'node:qb','relation':'relation:origin','target':'node:qa','scope':'scope:reported','evidence':['span:qa']}],
            'sources':[{'id':'source:qa','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}],
            'spans':[{'id':'span:qa','source':'source:qa','start':0,'end':len(text)}]}


class AuditAdapterTests(unittest.TestCase):
    def test_frame_premises_and_scope_are_authoritative(self):
        f=frame()
        rules=[{'id':'audit-link','version':1,'body':[['?x','relation:origin','?y']],
                'head':['?x','relation:derived','?y']}]
        target=['node:qa','relation:derived','node:qb']
        receipt=audit.audit_frame(f,rules,target,asserted_scope='scope:chosen')
        self.assertEqual(receipt['excluded_scope_edges'],['edge:qb'])
        self.assertTrue(receipt['audit']['verification']['conclusion_verified'])
        self.assertTrue(audit.verify_frame_audit(receipt,f,rules,target,asserted_scope='scope:chosen')['conclusion_verified'])
        changed=copy.deepcopy(f);changed['edges'][0]['scope']='scope:reported'
        self.assertFalse(audit.verify_frame_audit(receipt,changed,rules,target,asserted_scope='scope:chosen')['valid'])
        forged=copy.deepcopy(receipt);forged['audit']['conclusion']=['node:qb','relation:derived','node:qa']
        self.assertFalse(audit.verify_frame_audit(forged,f,rules,target,asserted_scope='scope:chosen')['valid'])

    def test_vm_replay_and_tamper(self):
        p=program();inputs={'number':17}
        result=audit.audit_vm(p,inputs,trace_limit=32)
        self.assertTrue(result['verification']['valid'])
        self.assertTrue(result['verification']['execution_completed'])
        forged=copy.deepcopy(result['execution']);forged['record']['steps'][1]['branch']=False
        self.assertFalse(audit.verify_vm_record(forged,p,inputs)['valid'])
        self.assertFalse(audit.verify_vm_record(result['execution'],p,{'number':18})['valid'])

    def test_record_cannot_choose_larger_replay_budget(self):
        p=program();inputs={'number':19}
        execution=audit.audit_vm(p,inputs)['execution']
        execution['record']['budget']=4097
        with mock.patch.object(audit,'run_recorded') as replay:
            self.assertFalse(audit.verify_vm_record(execution,p,inputs)['valid'])
            replay.assert_not_called()

    def test_incomplete_trace_does_not_verify(self):
        result=audit.audit_vm(program(),{'number':23},trace_limit=1)
        self.assertFalse(result['verification']['valid'])
        self.assertEqual(result['verification']['reason'],'incomplete')
