"""Regression checks for current-token rebinding and no uncertain input retry."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from mcp_backend import MCPBackend
from arc_cua.models import ActionKind,ExecutableAction
from arc_cua.errors import StaleDesktopState

class Fake:
    def __init__(self,rows):self.rows=rows;self.calls=[]
    def call(self,tool,**args):
        self.calls.append((tool,args))
        if tool=='get_window_state':return self.rows.pop(0),False
        return {},False

def state(token='s00000001:0',label='Submit'):
    return {'pid':7,'window_id':9,'elements':[{'element_index':0,'element_token':token,'role':'AXButton','label':label,'actions':['AXPress']}],'snapshot_id':token.split(':')[0]}

class BindingTests(unittest.TestCase):
    def test_refuses_changed_observed_control(self):
        fake=Fake([state(),state('s00000002:0','Delete'),state('s00000003:0','Delete')]);backend=MCPBackend(fake,'cua',7,9)
        snap=backend.observe();action=ExecutableAction(ActionKind.CLICK,target_id='ax_0',target_guard=snap.element('ax_0').semantic_guard())
        self.assertFalse(backend.is_fresh(snap,action))
        with self.assertRaises(StaleDesktopState):backend.execute(snap,action)
        self.assertFalse(any(c[0]=='click' for c in fake.calls))
    def test_dispatches_exact_new_token_once(self):
        fake=Fake([state(),state('s00000002:0')]);backend=MCPBackend(fake,'cua',7,9)
        snap=backend.observe();action=ExecutableAction(ActionKind.CLICK,target_id='ax_0',target_guard=snap.element('ax_0').semantic_guard())
        self.assertTrue(backend.is_fresh(snap,action));backend.execute(snap,action)
        self.assertEqual(fake.calls[-1],('click',{'pid':7,'window_id':9,'element_token':'s00000002:0'}))
        with self.assertRaises(StaleDesktopState):backend.execute(snap,action)
    def test_compound_key_can_prepare_a_fresh_revision(self):
        fake=Fake([state(),state('s00000002:0')]);backend=MCPBackend(fake,'cua',7,9)
        snap=backend.observe();action=ExecutableAction(ActionKind.PRESS_KEY,key='ENTER')
        backend.execute(snap,action)
        self.assertEqual(fake.calls[-1],('press_key',{'pid':7,'window_id':9,'key':'return'}))
    def test_type_text_compound_enter_executes_once(self):
        from arc_cua import DesktopExecutor,Subtask,TerminalKind
        from arc_cua.models import Decision
        class LiveFake:
            value=''
            mutations=[]
            def call(self,tool,**args):
                if tool=='get_window_state':
                    return {'pid':7,'window_id':9,'elements':[{'element_index':0,'element_token':'s00000001:0','role':'AXTextField','label':'Email','value':self.value,'actions':[]}]},False
                self.mutations.append(tool)
                if tool=='type_text':self.value=args['text']
                if tool=='press_key':self.key=args['key']
                return {},False
        class Policy:
            def decide(self,*,snapshot,history,subtask):
                if history:return Decision(terminal=TerminalKind.SUBTASK_COMPLETE)
                return Decision(kind=ActionKind.TYPE_TEXT,target_id='ax_0',input_key='email',key='ENTER')
        client=LiveFake();backend=MCPBackend(client,'cua',7,9)
        result=DesktopExecutor(backend,Policy()).run(Subtask(goal='Type supplied email then Enter',inputs={'email':'synthetic@example.invalid'},verification=('Email supplied and Enter pressed',)))
        self.assertEqual(result.status,TerminalKind.SUBTASK_COMPLETE)
        self.assertEqual(client.mutations,['type_text','press_key'])
        self.assertEqual(client.value,'synthetic@example.invalid')
        self.assertEqual(client.key,'return')
    def test_wrong_owner_refuses_observation(self):
        row=state();row['window_id']=10
        with self.assertRaises(StaleDesktopState):MCPBackend(Fake([row]),'cua',7,9).observe()

if __name__=='__main__':unittest.main()
