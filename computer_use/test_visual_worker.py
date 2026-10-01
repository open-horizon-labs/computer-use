import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('visual_worker',Path(__file__).resolve().parents[1]/'workers/visual_worker.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class VisualWireTests(unittest.TestCase):
    def test_pixels_and_constraints_survive_without_full_ax_dump(self):
        captured=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'model':'vision-test','answers':{'assessment':{'choice':'ready','vision':True}}}).encode()
        def send(req,timeout):captured.append(json.loads(req.data));return Response()
        row={'method':'inspect','snapshot_id':'s1','image':'data:image/png;base64,pixels',
             'postcondition':'Visible result','ax_text':'x'*34445,'constraints':{'retain':'all'}}
        with patch.dict(worker.os.environ,{'CUA_SYSTEMONE_URL':'http://test.invalid'}),patch.object(worker,'urlopen',send):
            result=worker.respond(row)
        self.assertEqual(result['state'],'ready')
        self.assertEqual(captured[0]['images'],[row['image']])
        self.assertNotIn('ax_text',captured[0]['state'])
        self.assertEqual(captured[0]['state']['constraints'],row['constraints'])
        self.assertEqual(captured[0]['state']['requested_outcome'],row['postcondition'])
        question=captured[0]['questions']['assessment']
        self.assertNotIn(row['postcondition'],question['criteria']['ready'])
        self.assertIn('Every stated constraint',question['instructions'])
        self.assertIn('only when explicitly requested',question['instructions'])
    def test_text_only_response_cannot_claim_visual_success(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'model':'text','answers':{'assessment':{'choice':'ready'}}}).encode()
        with patch.dict(worker.os.environ,{'CUA_SYSTEMONE_URL':'http://test.invalid'}),patch.object(worker,'urlopen',return_value=Response()):
            with self.assertRaises(ValueError):worker.respond({'method':'inspect','snapshot_id':'s1','image':'pixels','postcondition':'Ready'})


class NoUrlopen:
    """urlopen stand-in: any call fails the test, proving nothing was sent."""
    calls = 0
    def __call__(self, *args, **kwargs):
        NoUrlopen.calls += 1
        raise AssertionError('visual worker sent an HTTP request without CUA_SYSTEMONE_URL')


CHAT_ENV = {'QWEN_BASE_URL': 'http://chat.invalid/v1', 'QWEN_MODEL': 'qwen-test', 'QWEN_API_KEY': 'test-key'}


class NoChatFallbackTests(unittest.TestCase):
    def setUp(self):
        NoUrlopen.calls = 0

    def unset_env(self):
        env = {k: v for k, v in worker.os.environ.items() if k != 'CUA_SYSTEMONE_URL'}
        env.update(CHAT_ENV)
        return patch.dict(worker.os.environ, env, clear=True)

    def test_unset_url_sends_nothing_and_reports_unavailable_even_with_chat_config(self):
        # Wrong patch: "keep the fallback behind a flag that defaults on" (chat config present = fallback fires).
        rows = [{'method': 'inspect', 'snapshot_id': 's1', 'image': 'data:image/png;base64,p', 'postcondition': 'Ready'},
                {'method': 'choose', 'snapshot_id': 's1', 'image': 'data:image/png;base64,p', 'goal': 'g',
                 'candidates': {'a': 'A', 'abstain': 'none'}}]
        with self.unset_env(), patch.object(worker, 'urlopen', NoUrlopen()):
            for row in rows:
                with self.assertRaisesRegex(RuntimeError, 'visual_unavailable'):
                    worker.respond(row)
        self.assertEqual(NoUrlopen.calls, 0)

    def test_unset_url_returns_no_assessment_through_the_json_lines_loop(self):
        # Wrong patch: "fall back to text-only chat" (would return a state/choice built from chat content).
        import io
        line = json.dumps({'method': 'inspect', 'snapshot_id': 's1', 'image': 'x', 'postcondition': 'Ready'}) + '\n'
        out = io.StringIO()
        with self.unset_env(), patch.object(worker, 'urlopen', NoUrlopen()), \
                patch.object(worker.sys, 'stdin', io.StringIO(line)), patch.object(worker.sys, 'stdout', out):
            worker.main()
        reply = json.loads(out.getvalue())
        self.assertEqual(reply['snapshot_id'], 's1')
        self.assertIn('error', reply)
        self.assertNotIn('state', reply)
        self.assertEqual(NoUrlopen.calls, 0)

    def test_worker_has_no_chat_completion_code_path(self):
        # Wrong patch: leave the chat request in place, unreachable today but one env var from live.
        source = (Path(__file__).resolve().parents[1] / 'workers/visual_worker.py').read_text()
        for needle in ('chat/completions', 'QWEN_BASE_URL', 'QWEN_MODEL', 'image_url'):
            self.assertNotIn(needle, source)


from test_do import DoBase, rec, ONE


class VisualUnavailableEscalation(DoBase):
    def test_escalation_with_no_visual_provider_ends_unverified_and_sends_nothing(self):
        # Wrong patch: "fall back to text-only chat", or treat a missing provider as satisfied.
        # Real VisualTerminal validation over this worker's respond(), no SystemOne URL: chat is the only network route left.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference/cua-decider/capability-dispatch'))
        from terminal_observation import VisualTerminal
        class InProcessWorker:
            def exchange(self, payload, timeout=20):
                try:return worker.respond(payload)
                except Exception as error:return {'snapshot_id': payload.get('snapshot_id'), 'error': type(error).__name__}
            def close(self):pass
        def build():
            terminal = VisualTerminal.__new__(VisualTerminal);terminal.worker = InProcessWorker();return terminal
        NoUrlopen.calls = 0
        env = {k: v for k, v in worker.os.environ.items() if k != 'CUA_SYSTEMONE_URL'}
        env.update(CHAT_ENV)
        with patch.dict(worker.os.environ, env, clear=True), patch.object(worker, 'urlopen', NoUrlopen()):
            self.f.factories['visual'] = build
            self.driver.confirm_text = None
            r = self.do(records=rec(ONE), expect='Booking confirmed')
        self.assertEqual(NoUrlopen.calls, 0)
        self.assertNotEqual(r['status'], 'done')
        self.assertFalse(r['verified'])
        self.assertEqual(r['verification']['status'], 'unknown')
