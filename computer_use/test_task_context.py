"""Task routing must not mutate a shared facade or accept another task's evidence."""
import asyncio
import json
import unittest
from unittest.mock import patch
from task_context import Contexts
from core import Facade
from test_core import FakeDriver, FakeReader, FakeChooser, FakeVision
import server


def make(options):
    return Facade(FakeDriver(), reader_factory=FakeReader, generic_factory=FakeChooser,
                  visual_factory=FakeVision, sleep=lambda _: None,
                  on_behalf=options['session']=='user',
                  foreground_on_behalf=options['session']=='user' and options['presentation']=='visible')


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.registry = Contexts(make, clock=lambda: self.now, ttl=10, limit=3)
        self.default = make({'session':'isolated','presentation':'visible'})
        self.options = {'session':'user','presentation':'visible'}

    def tearDown(self):
        self.registry.close();self.default.close()

    def test_interleaved_contexts_keep_grants_and_looks_separate(self):
        a = self.registry.call(self.default, 'look', {'title':'Demo'}, self.options)
        b = self.registry.call(self.default, 'look', {'title':'Demo'}, {'session':'user','presentation':'background'})
        fa = self.registry.tasks[a['context_id']].facade
        fb = self.registry.tasks[b['context_id']].facade
        fa.fg_grants[(1,2,'Demo')] = True
        self.assertTrue(fa.foreground_on_behalf)
        self.assertFalse(fb.foreground_on_behalf)
        self.assertFalse(self.default.on_behalf)
        self.assertFalse(fb.fg_grants)
        self.assertNotEqual(a['look_id'],b['look_id'])
        wrong = self.registry.call(self.default,'do',{'goal':'Verify','expect':'Used $80','title':'Demo','operation':'verify','look_id':a['look_id']},context_id=b['context_id'])
        self.assertEqual(wrong['reason'],'context_look_mismatch')

    def test_look_handle_inherits_context_without_another_setup_call(self):
        seen = self.registry.call(self.default,'look',{'title':'Demo'},self.options)
        result = self.registry.call(self.default,'do',{'goal':'Inspect used','expect':None,'look_id':seen['look_id'], 'steps':[{'do':'verify','expect':'Used $80'}]})
        self.assertEqual(result['context_id'],seen['context_id'])
        self.assertEqual(result['status'],'observed')

    def test_context_resumes_exact_target_without_repeating_its_title(self):
        seen = self.registry.call(self.default,'look',{'title':'Demo'},self.options)
        again = self.registry.call(self.default,'look',{},context_id=seen['context_id'])
        self.assertEqual(again['status'],'ok')
        self.assertEqual(again['window'],seen['window'])

    def test_expired_context_never_falls_back_to_isolated_or_visible(self):
        seen = self.registry.call(self.default,'look',{'title':'Demo'},self.options)
        self.now = 11
        result = self.registry.call(self.default,'look',{'title':'Demo'},context_id=seen['context_id'])
        self.assertEqual(result['reason'],'context_expired_or_unknown')

    def test_cannot_reconfigure_existing_context_or_use_legacy_evidence(self):
        seen = self.registry.call(self.default,'look',{'title':'Demo'},self.options)
        conflict = self.registry.call(self.default,'look',{'title':'Demo'},self.options,seen['context_id'])
        self.assertEqual(conflict['reason'],'context_conflict')
        legacy = self.registry.call(self.default,'look',{'title':'Demo'})
        wrong = self.registry.call(self.default,'do',{'look_id':legacy['look_id']},context_id=seen['context_id'])
        self.assertEqual(wrong['reason'],'context_look_mismatch')

    def test_visible_action_fronts_exact_target_but_background_and_default_do_not(self):
        class Driver(FakeDriver):
            def __init__(self):
                super().__init__();self.sent=[]
            def call(self, tool, args, timeout=20):
                self.sent.append((tool,dict(args)))
                if tool == 'bring_to_front':return {'effect':'confirmed'}
                return super().call(tool,args)
        made=[]
        def factory(options):
            f=make(options);f.driver=Driver();made.append(f);return f
        self.registry.factory=factory
        for presentation in ('visible','background'):
            seen=self.registry.call(self.default,'look',{'title':'Demo'}, {'session':'user','presentation':presentation})
            self.assertFalse(any(t=='bring_to_front' for t,a in made[-1].driver.sent))
            result=self.registry.call(self.default,'do',dict(goal='Inspect first',control='Inspect first',expect=None,title='Demo'),context_id=seen['context_id'])
            self.assertEqual(result['status'],'delivered_unverified',result)
            sent=made[-1].driver.sent
            fronts=[a for t,a in sent if t=='bring_to_front']
            clicks=[a for t,a in sent if t=='click']
            self.assertTrue(clicks)
            self.assertEqual(bool(fronts),presentation=='visible')
            self.assertEqual(clicks[-1].get('delivery_mode'), 'foreground' if presentation=='visible' else None)
            if fronts:self.assertEqual((fronts[0]['pid'],fronts[0]['window_id']),(1,2))

    def test_visible_action_recovers_unreadable_target_before_selection(self):
        import test_live_shapes as lv
        from core import Gap
        class Driver(lv.LiveDriver):
            def __init__(self):
                super().__init__('live_booking_ax.json');self.front=False;self.script=lv.booked()
            def call(self, tool, args, timeout=20):
                if tool=='bring_to_front':
                    self.front=True;return {'effect':'confirmed'}
                return super().call(tool,args,timeout)
            def observe(self,*args):
                if not self.front:raise Gap('window_ax_unresolved: fixture requires activation')
                return super().observe(*args)
        f=make(self.options);f.driver=Driver()
        failed=f.look(title='Demo')
        self.assertEqual(failed['reason'],'window_ax_unresolved')
        self.assertFalse(f.driver.front)
        self.assertNotIn('Ask the user',failed['message'])
        result=f.do(goal='Book a visit',title='Demo',expect=None,control='Book')
        # Activation must precede AX observation, independently of selection ambiguity/provider availability.
        self.assertTrue(f.driver.front)
        self.assertNotEqual(result.get('reason'),'window_ax_unresolved',result)
        f.close()

    def test_verify_never_activates_visible_obo_target(self):
        f=make(self.options)
        with patch.object(f,'front_window') as front:
            f.do(goal='Check used product',title='Demo',expect='Used $80',operation='verify')
            front.assert_not_called()
        f.close()

    def test_isolated_url_look_never_attaches_to_user_browser_and_returns_navigation_hint(self):
        class Driver(FakeDriver):
            def __init__(self):super().__init__();self.sent=[]
            def call(self,tool,args,timeout=20):
                self.sent.append(tool)
                if tool=='list_windows':return {'windows':[{'pid':1,'window_id':2,'title':'User Chrome','app_name':'Google Chrome'}]}
                return super().call(tool,args,timeout)
        f=make({'session':'isolated','presentation':'visible'});f.context_session='isolated';f.driver=Driver()
        result=f.look(url='clinic.example')
        self.assertEqual(result['reason'],'window_not_found')
        self.assertEqual(result['who'],'agent')
        self.assertIn('goto',result['hint'])
        self.assertNotIn('get_browser_state',f.driver.sent)
        self.assertNotIn('browser_prepare',f.driver.sent)
        f.close()

    def test_background_conflict_is_explicit_and_not_a_silent_mode_change(self):
        seen=self.registry.call(self.default,'look',{'title':'Demo'}, {'session':'user','presentation':'background'})
        result=self.registry.call(self.default,'do',dict(goal='Inspect first',control='Inspect first',expect=None,title='Demo',allow_foreground=True),context_id=seen['context_id'])
        self.assertEqual(result['reason'],'presentation_conflict')
        self.assertEqual(result['context']['presentation'],'background')

    def test_obo_inventory_never_parks_user_apps(self):
        from unittest.mock import Mock
        f=make(self.options)
        f.agent=Mock()
        f.windows()
        f.agent.observed.assert_not_called()

    def test_obo_capability_refusals_do_not_ask_for_foreground_again(self):
        for presentation in ('visible','background'):
            f=make({'session':'user','presentation':presentation})
            r=f.mark({'status':'refused','reason':'pointer_not_deliverable_in_background'},'do')
            self.assertEqual(r['who'],'agent')
            self.assertNotIn('ask',r['hint'].lower())
            if presentation=='background':self.assertIn('placement conflict',r['hint'])
            grant=f.mark({'status':'refused','reason':'permission_required'},'do')
            self.assertEqual(grant['who'],'user')

    def test_captured_chrome_booking_completes_in_two_mcp_calls_in_both_presentations(self):
        import test_live_shapes as lv
        class Driver(lv.LiveDriver):
            def call(self, tool, args, timeout=20):
                if tool=='bring_to_front':return {'effect':'confirmed'}
                return super().call(tool,args,timeout)
        def factory(options):
            f=make(options);f.driver=Driver('live_booking_ax.json');f.driver.script=lv.booked();return f
        self.registry.factory=factory
        async def run():
            with patch.object(server,'contexts',self.registry), patch.object(server,'facade',self.default):
                for presentation in ('visible','background'):
                    async def call(tool,args):
                        response=await server.mcp.call_tool(tool,args)
                        return response[1] if isinstance(response,tuple) else json.loads(response[0].text)
                    seen=await call('look',{'title':'Demo','context':{'session':'user','presentation':presentation}})
                    self.assertEqual(seen['status'],'ok')
                    done=await call('do',{'goal':'Book the Follow-up with Dr. Morgan Reyes at 1:45 PM','expect':None,
                        'look_id':seen['look_id'], 'steps':[{'do':'press', 'where':{'lines':[
                        {'line':'eq','value':'Dr. Morgan Reyes'}, {'line':'eq','value':'Follow-up'},
                        {'line':'contains','value':'1:45 PM'}]}, 'control':'Book', 'expect':'Booked:'}]})
                    self.assertEqual(done['status'],'done',done)
                    self.assertEqual(self.registry.tasks[seen['context_id']].facade.first_do['calls'],2)
        asyncio.run(run())

    def test_context_handles_never_rewrite_extracted_page_fields(self):
        f=make(self.options)
        f.look=lambda **args: {'status':'ok','look_id':'lk_test','fields':{'look_id':'literal page value'}}
        self.registry.factory=lambda options:f
        seen=self.registry.call(self.default,'look',{},self.options)
        self.assertTrue(seen['look_id'].startswith(seen['context_id']+':'))
        self.assertEqual(seen['fields']['look_id'],'literal page value')

    def test_invalid_new_context_evidence_does_not_consume_capacity(self):
        result=self.registry.call(self.default,'do',{'look_id':'lk_legacy'},self.options)
        self.assertEqual(result['reason'],'context_look_mismatch')
        self.assertFalse(self.registry.tasks)

    def test_explicit_isolated_context_overrides_legacy_user_browser_default(self):
        import plan
        f=make({'session':'isolated','presentation':'visible'})
        f.context_session='isolated'
        f.agent_browser=type('Browser',(),{'mode':'user','window':lambda self,facade:(3,4)})()
        step={'do':'goto','url':'https://example.com'}
        self.assertTrue(plan.starts_on_agent_browser(f,[step]))
        target={'pid':None,'window_id':None}
        plan.resolve_browser_window(f,step,target,None)
        self.assertEqual((target['pid'],target['window_id']),(3,4))
        self.assertTrue(target['agent'])

    def test_identical_window_contents_do_not_alias_context_look_handles(self):
        f=make(self.options)
        def look(**args):
            pid=args['pid'];wid=args['window_id']
            f.looks[(pid,wid,'lk_same')]={'pid':pid,'window_id':wid}
            f.snapshots[str(pid)]={'pid':pid,'window_id':wid,'raw':{'window_title':'Same title'}}
            return {'status':'ok','look_id':'lk_same','window':{'title':'Same title'}}
        f.look=look
        f.do=lambda **args:{'status':'observed','target':[args['pid'],args['window_id']]}
        self.registry.factory=lambda options:f
        a=self.registry.call(self.default,'look',{'pid':1,'window_id':2},self.options)
        b=self.registry.call(self.default,'look',{'pid':3,'window_id':4},context_id=a['context_id'])
        self.assertNotEqual(a['look_id'],b['look_id'])
        result=self.registry.call(self.default,'do',{'look_id':a['look_id']})
        self.assertEqual(result['target'],[1,2])

    def test_real_mcp_schema_and_dispatch_support_context_and_defaults(self):
        async def run():
            with patch.object(server,'contexts',self.registry), patch.object(server,'facade',self.default):
                tools = await server.mcp.list_tools()
                self.assertEqual([t.name for t in tools],['do','look'])
                for tool in tools:
                    self.assertIn('context',tool.inputSchema['properties'])
                    self.assertIn('context_id',tool.inputSchema['properties'])
                response = await server.mcp.call_tool('look',{'title':'Demo','context':{'session':'user'}})
                # FastMCP returns content + structured response.
                result = response[1] if isinstance(response,tuple) else json.loads(response[0].text)
                self.assertEqual(result['context'],self.options)
                self.assertTrue(self.registry.tasks[result['context_id']].facade.foreground_on_behalf)
        asyncio.run(run())
