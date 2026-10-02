"""CE-FACADE-018: active routing must not revive archived paths. Offline only."""
import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import ValidationError
import server
from core import Gap
from task_context import Contexts, Task
from test_mobile import overview_backend, facade_for, EMULATOR


def body(result):
    if hasattr(result,'structuredContent'):return result.structuredContent
    if isinstance(result,tuple):return result[1]
    return json.loads(result[0].text)

class NativeFirst(unittest.TestCase):
    def setUp(self):
        self.backend=overview_backend()
        self.f=facade_for(self.backend)
        self.f.driver.call=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('no Mac I/O'))
        self.registry=Contexts(lambda options: self.f)
        self.addCleanup(self.registry.close)
        self.patches=[patch.object(server,'facade',self.f),patch.object(server,'contexts',self.registry)]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def test_native_default_does_no_observation_or_input_even_with_device(self):
        self.assertEqual(server.look(device=EMULATOR).get('reason'),'native_default')
        self.assertEqual(server.do('Open Networks',[{'do':'press','control':'Networks'}],device=EMULATOR).get('reason'),'native_default')
        self.assertEqual(self.backend.calls,[])
        self.assertEqual(self.registry.tasks,{})

    def test_mobile_requires_selection_and_verifies_with_bound_context(self):
        self.assertEqual(server.look(capability='mobile')['reason'],'device_required')
        seen=server.look(capability='mobile',device=EMULATOR)
        done=server.do('Open Networks',[{'do':'press','control':'Networks','expect':'Saved networks'}],
                       capability='mobile',context_id=seen['context_id'],look_id=seen['look_id'])
        self.assertEqual(done['status'],'done',done)
        self.assertEqual(self.backend.tapped,['Networks'])
        self.assertEqual(self.registry.tasks[seen['context_id']].target,{'device':EMULATOR})

    def test_filters_without_sight_and_cross_capability_handles_refuse(self):
        seen=server.look(capability='mobile',device=EMULATOR)
        before=len(self.backend.tapped)
        blind=server.do('Forget Office',[{'do':'press','where':{'lines':[{'line':'eq','value':'Office'}]},'expect':'Office forgotten'}],capability='mobile',context_id=seen['context_id'])
        self.assertEqual(blind['reason'],'look_required',blind)
        cross=server.do('Wrong route',[{'do':'press','control':'Networks'}],capability='off_screen',look_id=seen['look_id'])
        self.assertEqual(cross['reason'],'context_capability_mismatch')
        self.assertEqual(len(self.backend.tapped),before)

    def test_schema_rejects_archived_fields_steps_and_observation_targets(self):
        for key in ('profile','allow_foreground','argv','fields','files','menu'):
            with self.assertRaises(ValidationError):server.Step.model_validate({'do':'press',key:True})
        for name in ('terminal','read_pages','upload','resize'):
            with self.assertRaises(ValidationError):server.Step.model_validate({'do':name})
        for tool in asyncio.run(server.mcp.list_tools()):
            self.assertFalse({'title','pid','window_id','terminal','context','records','fields','allow_foreground'} & tool.inputSchema['properties'].keys())
        self.assertEqual(server.do('Archived',[{'do':'launch','app':'com.apple.TextEdit'}],capability='off_screen')['reason'],'off_screen_session_required')
        self.assertEqual(self.backend.calls,[])

    def test_off_screen_needs_owned_session_and_one_context(self):
        self.assertEqual(server.look(capability='off_screen')['reason'],'off_screen_session_required')
        self.f.agent_browser=SimpleNamespace(proc=SimpleNamespace(pid=99),window_id=100)
        self.f.do=lambda **kw: {'status':'delivered_unverified'}
        opened=server.do('Open',[{'do':'open_tab','url':'https://example.com'}],capability='off_screen')
        ctx=opened['context_id']
        self.assertEqual(self.registry.tasks[ctx].target,{'pid':99,'window_id':100})
        self.assertEqual(server.do('Second task',[{'do':'goto','url':'https://other.example'}],capability='off_screen').get('reason'),'off_screen_context_busy')
        self.assertEqual(self.backend.calls,[])

    def test_actual_handle_target_must_match_owned_browser_even_when_latest_target_matches(self):
        self.f.agent_browser=SimpleNamespace(proc=SimpleNamespace(pid=99),window_id=100)
        task=Task(self.f,{'capability':'off_screen'},self.registry.clock(),{'pid':99,'window_id':100})
        task.handles['ctx_a:old']={'raw':'lk_old','target':{'pid':1,'window_id':2}}
        self.registry.tasks['ctx_a']=task
        r=server.do('Stale',[{'do':'press','control':'Submit'}],capability='off_screen',look_id='ctx_a:old')
        self.assertEqual(r['reason'],'off_screen_target_mismatch')
        task.target={'pid':99,'window_id':101}
        r=server.look(capability='off_screen',context_id='ctx_a')
        self.assertEqual(r['reason'],'off_screen_target_mismatch')
        self.assertEqual(self.backend.calls,[])

    def test_expired_or_cross_context_handles_never_choose_a_new_target(self):
        seen=server.look(capability='mobile',device=EMULATOR)
        r=server.do('Cross',[{'do':'press','control':'Networks'}],capability='mobile',context_id='ctx_other',look_id=seen['look_id'])
        self.assertEqual(r['reason'],'context_look_mismatch')
        self.assertEqual(self.backend.tapped,[])

    def test_vnc_and_model_routes_are_disabled(self):
        with self.assertRaises(Gap):server.unavailable()
        with patch('novnc.surface',return_value={'semantic':{}}):
            refused,surface=server.OptInFacade._novnc_gate(self.f,99,100,'s',{})
        self.assertIsNotNone(refused)
        self.assertEqual(refused.get('reason'),'use_native');self.assertIsNone(surface)

    def test_policy_empty_allowlist_and_legacy_env_cannot_revive_routes(self):
        policy=json.loads((Path(__file__).parent/'ROUTES.json').read_text())
        self.assertEqual(policy['automatic_oh_routes'],[])
        self.assertEqual(policy['opt_in'],['mobile','off_screen'])
        import call_budget
        self.assertEqual(call_budget.advanced_tool_names(),['do','look'])
        code="import json,server;print(json.dumps([server.facade.agent_browser.mode,server.facade.agent.mode]))"
        import os,subprocess,sys
        done=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,env={**os.environ,'CUA_AGENT_BROWSER':'user','CUA_AGENT_DISPLAY':'off'},capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(done.stdout),['auto','required'])

if __name__=='__main__':unittest.main()
