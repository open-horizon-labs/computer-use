"""Real tu-captured grid, fake transport: no subprocess, GUI, model or network."""
import asyncio
import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

from core import Facade, Gap
from task_context import Contexts
from terminal import Terminal, TuDriver, key_bytes
import server

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/terminal_menu.json').read_text())


class FakeTu:
    def __init__(self):
        self.states = {}
        self.calls = []
        self.started = False
        self.closed = False
        self.after_input = lambda state, request: None
        self.fail = None

    def start(self, deadline):self.started = True
    def close(self):self.closed = True
    def request(self, request, deadline):
        self.calls.append(copy.deepcopy(request))
        kind, name = request['type'], request.get('name')
        if self.fail == kind:raise Gap('terminal_transport_failed: incomplete response')
        if kind == 'Run':
            self.states[name] = copy.deepcopy(FIXTURE)
            self.states[name]['Status']['name'] = name
            return {'type':'SessionCreated','name':name,'pid':12345}
        if kind == 'List':return {'type':'SessionList','sessions':[s['Status'] for s in self.states.values()]}
        if kind == 'Kill':del self.states[name];return {'type':'Ok'}
        if kind in ('Press', 'Type'):
            self.after_input(self.states[name], request)
            return {'type':'Ok'}
        return copy.deepcopy(self.states[name][kind])

    def png(self, name, deadline):
        return (Path(__file__).parent / 'fixtures/live_booking_screen.png').read_bytes()

    @property
    def inputs(self):return [r for r in self.calls if r['type'] in ('Run','Press','Type','Kill')]


def make():
    return Facade(driver=Mock(side_effect=AssertionError('GUI must not run')), terminal=Terminal(FakeTu()))


def launch(f):
    return f.do(goal='Open test menu', terminal='new', steps=[{'do':'launch','argv':['/bin/example','a;$(literal)'],'cwd':'/tmp','width':80,'height':24,'expect':'READY'}])


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.f = make();self.addCleanup(self.f.close)
        self.first = launch(self.f)
        self.name = self.first['terminal']
        self.driver = self.f._terminal.driver
        self.state = self.driver.states[self.name]
        self.driver.calls.clear()

    def act(self, steps, **args):
        args.setdefault('budget_s', .1)
        return self.f.do(goal='Choose', terminal=self.name, look_id=self.first['look_id'], steps=steps, **args)

    def test_launch_passes_literal_argv_and_cwd_without_shell(self):
        f=make();self.addCleanup(f.close);launch(f)
        request=f._terminal.driver.inputs[0]
        self.assertEqual(request['command'],'/bin/example')
        self.assertEqual(request['args'],['a;$(literal)'])
        self.assertEqual(request['cwd'],'/tmp')
        self.assertIs(request['shell'],False)
        self.assertEqual(self.first['status'],'done')
        self.assertEqual(self.first['lines'][1],{'row':1,'text':'Alpha'})
        self.assertIn('7mAlpha',self.first['styled_rows'][0]['ansi'])
        self.f.driver.call.assert_not_called()
        self.assertEqual(self.f.providers,{})

    def test_changed_text_style_or_cursor_prevents_input(self):
        for change in ('text','style','cursor','pid'):
            self.driver.states[self.name]=copy.deepcopy(self.state)
            current=self.driver.states[self.name]
            if change=='text':current['ScreenshotCells']['rows_ansi'][0]='Another menu'
            if change=='style':current['ScreenshotCells']['rows_ansi'][1]=current['ScreenshotCells']['rows_ansi'][1].replace(';7m',';1m')
            if change=='cursor':current['Cursor']['col']=1
            if change=='pid':current['Status']['pid']=999
            out=self.act([{'do':'press','control':'Enter','expect':'ACCEPTED Beta'}])
            self.assertEqual(out['status'],'refused',out)
            self.assertEqual(out['delivery'],'none',out)
            self.assertEqual(self.driver.inputs,[])
        # A returned replacement look from a stale screen permits a deliberate new action.
        out=self.f.look(terminal=self.name)
        self.assertEqual(out['reason'],'terminal_identity_mismatch')

    def test_stale_refusal_returns_usable_fresh_handle(self):
        self.state['Cursor']['col']=1
        out=self.act([{'do':'press','control':'Down'}])
        self.assertEqual(out['reason'],'terminal_changed_since_look')
        fresh=self.f.do(goal='Choose',terminal=self.name,look_id=out['look_id'],steps=[{'do':'press','control':'Down'}])
        self.assertEqual(fresh['status'],'delivered_unverified')
        self.assertEqual(len(self.driver.inputs),1)

    def test_unknown_or_other_terminal_look_never_sends_input(self):
        other=launch(self.f);self.driver.calls.clear()
        for name, token in [(self.name,'unknown'),(other['terminal'],self.first['look_id']),('term_foreign',self.first['look_id'])]:
            out=self.f.do(goal='Choose',terminal=name,look_id=token,steps=[{'do':'press','control':'Enter'}])
            self.assertEqual(out['status'],'refused',out)
        self.assertEqual(self.driver.inputs,[])

    def test_no_look_no_input(self):
        out=self.f.do(goal='Choose',terminal=self.name,steps=[{'do':'press','control':'Enter'}])
        self.assertEqual(out['reason'],'look_required')
        self.assertEqual(self.driver.inputs,[])

    def test_entire_plan_validated_before_first_write(self):
        bad=[{'do':'press','control':'MadeUp'}, {'do':'type','text':'bad\ncommand'}, {'do':'press','control':'Enter','where':{}}, {'do':'launch','argv':['x'],'cwd':'/tmp'}, {'do':'close','expect':'bye'}]
        for step in bad:
            out=self.act([{'do':'press','control':'Enter','expect':'ACCEPTED Beta'},step])
            self.assertEqual(out['status'],'refused',out)
        self.assertEqual(self.driver.inputs,[])

    def test_preexisting_or_echoed_text_is_not_success_and_stops_chain(self):
        for step in [{'do':'press','control':'Enter','expect':'READY'}, {'do':'type','text':'ACCEPTED Beta','expect':'ACCEPTED Beta'}]:
            self.driver.after_input=lambda s,r:s['ScreenshotCells']['rows_ansi'].__setitem__(3,'ACCEPTED Beta') if r['type']=='Type' else None
            self.driver.states[self.name]=copy.deepcopy(self.state)
            self.first=self.f.look(terminal=self.name)
            out=self.act([step,{'do':'press','control':'q'}])
            self.assertEqual(out['status'],'delivered_unverified',out)
            self.assertEqual(len(out['steps']),1)
        self.assertEqual(len(self.driver.inputs),2)

    def test_delayed_echo_after_enter_is_not_task_success(self):
        self.act([{'do':'type','text':'ACCEPTED Beta'}])
        self.first=self.f.look(terminal=self.name)
        self.driver.after_input=lambda s,r:s['ScreenshotCells']['rows_ansi'].__setitem__(3,'ACCEPTED Beta')
        out=self.act([{'do':'press','control':'Enter','expect':'ACCEPTED Beta'}])
        self.assertEqual(out['status'],'delivered_unverified',out)
        observed=self.f.do(goal='Read evidence only',terminal=self.name,steps=[{'do':'verify','expect':'ACCEPTED Beta'}])
        self.assertEqual(observed['status'],'observed')

    def test_new_postcondition_requires_independent_read(self):
        self.driver.after_input=lambda s,r:s['ScreenshotCells']['rows_ansi'].__setitem__(3,'ACCEPTED Beta')
        out=self.act([{'do':'press','control':'Enter','expect':'ACCEPTED Beta'}])
        self.assertEqual(out['status'],'done',out)
        calls=[r['type'] for r in self.driver.calls]
        self.assertIn('ScreenshotCells',calls[calls.index('Press')+1:])
        self.assertEqual(len(self.driver.inputs),1)

    def test_delivery_failure_never_retries(self):
        self.driver.fail='Press'
        out=self.act([{'do':'press','control':'Enter','expect':'ACCEPTED Beta'}])
        self.assertEqual(out['delivery'],'uncertain')
        self.assertEqual(out['status'],'failed')
        self.assertEqual(len(self.driver.inputs),1)

    def test_unchanged_output_and_exited_process_do_not_claim_success(self):
        out=self.act([{'do':'press','control':'Enter','expect':'never'}],budget_s=.1)
        self.assertEqual(out['status'],'delivered_unverified',out)
        self.assertEqual(len(self.driver.inputs),1)
        self.state['Status']['alive']=False;self.state['Status']['exit_code']=7
        self.first=self.f.look(terminal=self.name)
        out=self.act([{'do':'press','control':'Enter'}])
        self.assertEqual(out['reason'],'terminal_exited')
        self.assertEqual(len(self.driver.inputs),1)

    def test_close_verifies_absence_and_preserves_other_owned_session(self):
        other=launch(self.f)
        out=self.act([{'do':'close'}])
        self.assertTrue(out['closed'])
        self.assertEqual(out['status'],'done')
        self.assertEqual(self.f.look(terminal='list')['terminals'],[other['terminal']])
        self.assertEqual(self.f.look(terminal=self.name)['reason'],'terminal_not_found')
        self.f.close();self.assertTrue(self.driver.closed)

    def test_malformed_grid_is_not_action_evidence(self):
        for key,value in [('rows',25),('cols',0),('rows_ansi',['wrong'])]:
            self.driver.states[self.name]=copy.deepcopy(self.state)
            self.driver.states[self.name]['ScreenshotCells'][key]=value
            out=self.act([{'do':'press','control':'Enter'}])
            self.assertEqual(out['reason'],'terminal_snapshot_invalid',out)
        self.assertEqual(self.driver.inputs,[])

    def test_refuses_mixed_targets_and_on_behalf_before_any_driver_access(self):
        for args in ({'title':'Ghostty'},{'url':'example.com'},{'device':'phone'},{'fields':{}},{'focus':'ready'}):
            out=self.f.look(terminal=self.name,**args)
            self.assertEqual(out['reason'],'bad_request',out)
        self.f.on_behalf=True
        self.assertEqual(self.f.look(terminal=self.name)['reason'],'terminal_context_unsupported')
        self.assertEqual(self.driver.calls,[])

    def test_bounded_output_discloses_omissions(self):
        self.state['ScreenshotCells']['rows_ansi']=['\x1b[31m'+('x'*80)+'\x1b[0m']*24
        out=self.f.look(terminal=self.name,max_bytes=1000)
        # Facade appends metadata after the driver's own bounded text envelope.
        self.assertGreater(out['truncated']['lines'],0)
        self.assertGreater(out['truncated']['styled_rows'],0)
        self.assertLess(len(json.dumps(out)),1300)

    def test_driver_version_missing_and_dead_daemon_have_actionable_refusals(self):
        f=Facade(terminal=Terminal(TuDriver('/path/does/not/exist')));self.addCleanup(f.close)
        out=launch(f)
        self.assertEqual(out['reason'],'terminal_driver_missing')
        self.assertIn('install_terminal.py',out['message'])
        d=TuDriver();d.process=Mock();d.process.poll.return_value=1
        with patch('terminal.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(Gap,'terminal_driver_lost'):d.start(time.monotonic()+1)
            spawn.assert_not_called()

    def test_key_encoding_supports_tui_controls_without_shell_syntax(self):
        for key,expected in [('Down',b'\x1bOB'),('Enter',b'\r'),('Ctrl+C',b'\x03'),('Alt+x',b'\x1bx'),('é','é'.encode())]:
            self.assertEqual(bytes(key_bytes(key)),expected)
        with self.assertRaises(Gap):key_bytes('Enter;rm')

    def test_png_daemon_loss_rejects_capture_and_reaps_only_renderer_group(self):
        driver=TuDriver();driver.env={'XDG_RUNTIME_DIR':'/private/fixture'}
        driver.process=Mock();driver.process.poll.side_effect=[None,1]
        renderer=Mock(pid=4455,returncode=0);renderer.communicate.return_value=(b'pixels',b'')
        with patch('terminal.subprocess.Popen',return_value=renderer) as spawn,patch('terminal.os.killpg') as kill:
            with self.assertRaisesRegex(Gap,'terminal_driver_lost'):driver.png(self.name,time.monotonic()+1)
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual(kill.call_args.args[0],renderer.pid)


class TerminalContextTests(unittest.TestCase):
    def setUp(self):
        self.default=make();self.contexts=Contexts(lambda _:make())
        self.addCleanup(self.default.close);self.addCleanup(self.contexts.close)

    def open(self):
        return self.contexts.call(self.default,'do',{'goal':'menu','terminal':'new','steps':[{'do':'launch','argv':['/bin/demo'],'cwd':'/tmp','expect':'READY'}]},context={'session':'isolated'})

    def test_resume_and_cross_context_binding(self):
        a=self.open();b=self.open()
        wrong=self.contexts.call(self.default,'do',{'goal':'read','look_id':a['look_id'],'steps':[{'do':'verify','expect':'READY'}]},context_id=b['context_id'])
        self.assertEqual(wrong['reason'],'context_look_mismatch')
        resumed=self.contexts.call(self.default,'do',{'goal':'read','look_id':a['look_id'],'steps':[{'do':'verify','expect':'READY'}]})
        self.assertEqual(resumed['terminal'],a['terminal'])
        self.assertEqual(resumed['status'],'observed')
        foreign=self.contexts.call(self.default,'look',{'terminal':a['terminal']},context_id=b['context_id'])
        self.assertEqual(foreign['reason'],'terminal_not_found')
        seen=self.contexts.call(self.default,'look',{},context_id=a['context_id'])
        self.assertEqual(seen['terminal'],a['terminal'])

    def test_stale_context_handle_rebinds_to_terminal_not_old_gui_target(self):
        a=self.open();task=self.contexts.tasks[a['context_id']]
        task.target={'title':'old GUI'}
        task.facade._terminal.driver.states[a['terminal']]['Cursor']['col']=1
        stale=self.contexts.call(self.default,'do',{'goal':'press','look_id':a['look_id'],'steps':[{'do':'press','control':'Enter'}]})
        self.assertEqual(stale['reason'],'terminal_changed_since_look')
        out=self.contexts.call(self.default,'do',{'goal':'press','look_id':stale['look_id'],'steps':[{'do':'press','control':'Enter'}]})
        self.assertEqual(out['terminal'],a['terminal'])
        self.assertEqual(out['status'],'delivered_unverified')

    def test_real_mcp_look_do_schema_and_image_transport(self):
        async def run():
            with patch.object(server,'facade',self.default),patch.object(server,'contexts',self.contexts):
                result=await server.mcp.call_tool('do',{'goal':'menu','expect':None,'terminal':'new','steps':[{'do':'launch','argv':['/bin/demo'],'cwd':'/tmp','expect':'READY'}]})
                out=result[1] if isinstance(result,tuple) else json.loads(result[0].text)
                name=out['terminal']
                result=await server.mcp.call_tool('look',{'terminal':name})
                out=result[1] if isinstance(result,tuple) else json.loads(result[0].text)
                self.assertEqual(out['source'],'terminal_use')
                self.assertIn('look_id',out)
                image=await server.mcp.call_tool('look',{'terminal':name,'screen':True})
                self.assertEqual([b.type for b in image.content],['text','image'])
                self.assertFalse(image.structuredContent['image']['action_binding'])
                self.assertEqual([t.name for t in await server.mcp.list_tools()],['do','look'])
        asyncio.run(run())


if __name__=='__main__':unittest.main()
