"""Offline tests: scorer, monitor display containment and detector, task ground truth, server, prompts, runner gates.
No desktop, no claude, no network. Run: python3 -m unittest discover -s experiments/surfaces-ab -p 'test_*.py'
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx
import monitor
import runner
import score
import server
import surfaces
import tasks

USER = {'id': 1, 'x': 0, 'y': 0, 'width': 2000, 'height': 1200, 'virtual': False, 'main': True}
AGENT = {'id': 9, 'x': 2000, 'y': 0, 'width': 1920, 'height': 1080, 'virtual': True}
DISPLAYS = [USER, AGENT]


def win(i, x, y, w=800, h=600, owner='App', title='t'):
    return {'id': i, 'pid': 100 + i, 'owner': owner, 'title': title, 'x': x, 'y': y, 'width': w, 'height': h}


def sample(t, front=1, windows=(), cursor=(500, 500), displays=DISPLAYS, name=None):
    return {'t': t, 'front': {'pid': front, 'name': name or 'app%d' % front}, 'windows': list(windows),
            'cursor': {'x': cursor[0], 'y': cursor[1]}, 'displays': displays}


class ContainmentTest(unittest.TestCase):
    def test_wholly_inside_agent_display_is_agent(self):
        self.assertEqual(monitor.classify_window(win(1, 2040, 40, 1840, 1000), DISPLAYS), 'agent')

    def test_overlap_with_real_display_is_user(self):
        self.assertEqual(monitor.classify_window(win(1, 100, 100), DISPLAYS), 'user')

    def test_straddling_agent_and_real_counts_as_user(self):
        self.assertEqual(monitor.classify_window(win(1, 1500, 100, 1000, 500), DISPLAYS), 'user')

    def test_agent_window_hanging_off_the_agent_display_edge_is_not_agent(self):
        self.assertEqual(monitor.classify_window(win(1, 3000, 100, 1200, 500), DISPLAYS), 'offscreen')

    def test_agent_id_override_marks_a_non_virtual_display(self):
        self.assertEqual(monitor.classify_window(win(1, 100, 100), [dict(USER)], agent_ids=(1,)), 'agent')

    def test_display_of_cursor(self):
        self.assertEqual(monitor.display_of((10, 10), DISPLAYS), 'user')
        self.assertEqual(monitor.display_of((2100, 10), DISPLAYS), 'agent')
        self.assertEqual(monitor.display_of((9999, 10), DISPLAYS), 'none')


class DetectorTest(unittest.TestCase):
    def run_samples(self, samples):
        d = monitor.Detector()
        for s in samples:
            d.feed(s)
        return d

    def test_baseline_windows_and_focus_never_count(self):
        d = self.run_samples([sample(0, windows=[win(1, 0, 0)]), sample(1, windows=[win(1, 0, 0)])])
        self.assertEqual(d.events, [])
        self.assertEqual(d.summary()['new_user_windows'], 0)

    def test_new_window_on_user_screen_counts_once(self):
        d = self.run_samples([sample(0), sample(1, windows=[win(5, 200, 200)]), sample(2, windows=[win(5, 200, 200)]), sample(3)])
        s = d.summary()
        self.assertEqual(s['new_user_windows'], 1)
        self.assertEqual(d.events[0]['kind'], 'new_user_window')

    def test_new_window_wholly_on_agent_display_does_not_count(self):
        d = self.run_samples([sample(0), sample(1, windows=[win(5, 2040, 40, 1800, 1000)])])
        self.assertEqual(d.summary()['new_user_windows'], 0)
        self.assertEqual(d.summary()['new_agent_windows'], 1)

    def test_window_that_moves_from_agent_display_onto_user_screen(self):
        d = self.run_samples([sample(0), sample(1, windows=[win(5, 2040, 40, 1800, 1000)]), sample(2, windows=[win(5, 300, 40, 1800, 1000)])])
        self.assertEqual(d.summary()['windows_to_user_display'], 1)

    def test_tiny_windows_and_driver_overlays_are_separate(self):
        d = self.run_samples([sample(0), sample(1, windows=[win(5, 10, 10, 20, 20), win(6, 0, 0, 2000, 1200, owner='Cua Driver')])])
        s = d.summary()
        self.assertEqual((s['new_user_windows'], s['overlay_windows']), (0, 1))

    def test_focus_steal_vs_return(self):
        d = self.run_samples([sample(0, front=1), sample(1, front=2), sample(2, front=1), sample(3, front=3)])
        s = d.summary()
        self.assertEqual(s['focus_changes'], 3)
        self.assertEqual(s['focus_steals'], 2)  # the return to the starting app (pid 1) is not a steal
        self.assertTrue(d.events[0]['steal'] and not d.events[1]['steal'])

    def test_cursor_noise_ignored_and_bursts_grouped(self):
        pts = [(500, 500), (500.5, 500), (600, 500), (700, 500), (700, 500), (700, 500), (900, 500)]
        d = monitor.Detector()
        t = 0.0
        for p in pts:
            d.feed(sample(t, cursor=p))
            t += 0.5
        s = d.summary()
        self.assertEqual(s['cursor_move_samples'], 3)
        self.assertEqual(s['cursor_px'], 400)
        self.assertEqual(s['cursor_bursts'], 2)  # a stillness longer than BURST_GAP_S splits the bursts

    def test_cursor_on_agent_display_is_flagged(self):
        d = self.run_samples([sample(0, cursor=(500, 500)), sample(0.2, cursor=(2500, 500))])
        self.assertEqual(d.summary()['cursor_moves_on_agent_display'], 1)
        self.assertEqual(d.events[0]['on'], 'agent')

    def test_annoyances_are_readable(self):
        d = self.run_samples([sample(0, name='Terminal'), sample(1, front=2, name='Calculator', windows=[win(5, 10, 10, owner='Calculator', title='Calculator')]),
                              sample(1.2, front=2, name='Calculator', windows=[win(5, 10, 10, owner='Calculator', title='Calculator')], cursor=(900, 900))])
        notes = monitor.annoyances(d.events, d.summary())
        self.assertTrue(any('Calculator took focus from Terminal' in n for n in notes))
        self.assertTrue(any('new window on your screen: Calculator "Calculator"' in n for n in notes))
        self.assertTrue(any('cursor moved' in n for n in notes))

    def test_monitor_process_writes_timeline(self):
        script = ('import json,time\nfor i in range(4):\n print(json.dumps({"t":1000+i*0.2,"front":{"pid":1,"name":"a"},"cursor":{"x":%d,"y":0},'
                  '"displays":[],"windows":[]}),flush=True)\n time.sleep(0.05)\ntime.sleep(5)\n') % 0
        with tempfile.TemporaryDirectory() as tmp:
            m = monitor.Monitor(Path(tmp) / 'tl.jsonl', command=[sys.executable, '-c', script])
            m.start()
            import time
            time.sleep(0.4)
            summary = m.stop()
            self.assertTrue(summary['monitor_ok'])
            self.assertGreaterEqual(summary['samples'], 2)
            self.assertTrue((Path(tmp) / 'tl.jsonl').exists())


class EventTaskTest(unittest.TestCase):
    def ev(self, action, ident='', values=None, ts=1):
        e = {'ts': ts, 'action': action, 'id': ident}
        if values is not None:
            e['values'] = values
        return e

    def test_booking(self):
        self.assertEqual(tasks.judge('booking', events=[self.ev('book', 's10')])[0], 'correct')
        self.assertEqual(tasks.judge('booking', events=[self.ev('book', 's07')])[0], 'wrong')
        self.assertEqual(tasks.judge('booking', events=[self.ev('book', 's10', ts=1), self.ev('book', 's07', ts=2)])[0], 'wrong')
        self.assertEqual(tasks.judge('booking', events=[])[0], 'no-action')
        self.assertEqual(tasks.judge('booking', events=[], timed_out=True)[0], 'timeout')

    def test_orders_needs_confirm(self):
        req, conf = self.ev('cancel_request', '1044', ts=1), self.ev('cancel_confirm', '1044', ts=2)
        self.assertEqual(tasks.judge('orders', events=[req, conf])[0], 'correct')
        self.assertEqual(tasks.judge('orders', events=[req])[0], 'failed')  # acted, never completed
        self.assertEqual(tasks.judge('orders', events=[self.ev('cancel_request', '1042')])[0], 'wrong')

    def test_form_exact_values(self):
        good = self.ev('submit', 'intake', dict(fx.FORM_VALUES))
        self.assertEqual(tasks.judge('form', events=[good])[0], 'correct')
        bad = self.ev('submit', 'intake', dict(fx.FORM_VALUES, phone='555-0000'))
        self.assertEqual(tasks.judge('form', events=[bad])[0], 'wrong')
        self.assertEqual(tasks.judge('form', events=[bad, dict(good, ts=2)])[0], 'wrong')

    def test_upload_compares_filename_size_and_hash(self):
        want = {'filename': 'a.txt', 'size': 10, 'sha256': 'abc'}
        up = lambda **v: self.ev('upload', 'attachment', dict({'filename': 'a.txt', 'size': '10', 'sha256': 'abc'}, **v))
        self.assertEqual(tasks.judge('upload', events=[up()], truth=want)[0], 'correct')
        self.assertEqual(tasks.judge('upload', events=[up(sha256='zzz')], truth=want)[0], 'wrong')
        self.assertEqual(tasks.judge('upload', events=[], truth=want)[0], 'no-action')


class TextTaskTest(unittest.TestCase):
    def j(self, task, text, truth, acted=True):
        return tasks.judge(task, text=text, truth=truth, acted=acted)[0]

    def test_compare_requires_in_stock_item_and_no_decoy_price(self):
        truth = {'name': 'Quillon Arc Lamp', 'price': '36.75'}
        self.assertEqual(self.j('compare', 'The Quillon Arc Lamp at $36.75.', truth), 'correct')
        self.assertEqual(self.j('compare', 'Marlow Banker Lamp, $29.00', truth), 'wrong')
        self.assertEqual(self.j('compare', 'Quillon Arc Lamp $36.75 (the Marlow at $29.00 is out of stock)', truth), 'correct')  # relaxed 2026-10-01 after the first run, see README (both arms explained the decoys)
        self.assertEqual(self.j('compare', 'I could not do it', truth, acted=False), 'no-action')

    def test_number_answers_ignore_separators(self):
        self.assertEqual(self.j('wikipedia', 'It is 8,848.86 m (29,031.7 ft).', '8848.86'), 'correct')
        self.assertEqual(self.j('wikipedia', 'About 8,849 m', '8848.86'), 'wrong')
        self.assertEqual(self.j('calculator', 'The display shows 1,316', '1316'), 'correct')
        self.assertEqual(self.j('calculator', 'It shows 1316.0', '1316'), 'correct')
        self.assertEqual(self.j('calculator', 'It shows 1,361', '1316'), 'wrong')

    def test_versions(self):
        self.assertEqual(self.j('android', 'Android version 15', '15'), 'correct')
        self.assertEqual(self.j('android', 'Android 15.0 (API 35)', '15'), 'correct')
        self.assertEqual(self.j('android', 'Android 14', '15'), 'wrong')
        self.assertEqual(self.j('ios', 'iOS Version 26.5', '26.5'), 'correct')
        self.assertEqual(self.j('ios', 'iOS 26.2', '26.5'), 'wrong')

    def test_textedit_document(self):
        self.assertEqual(tasks.judge('textedit', doc=tasks.TEXTEDIT_SENTENCE + '\n', acted=True)[0], 'correct')
        self.assertEqual(tasks.judge('textedit', doc='something else', acted=True)[0], 'wrong')
        self.assertEqual(tasks.judge('textedit', doc=None, acted=True)[0], 'failed')  # acted, left no document
        self.assertEqual(tasks.judge('textedit', doc=None, acted=False)[0], 'no-action')
        self.assertEqual(tasks.judge('textedit', doc='', acted=True, timed_out=True)[0], 'timeout')


class ProbeTest(unittest.TestCase):
    INFOBOX = ('<tr><th class="infobox-header">Highest&#160;point</th></tr><tr><th scope="row" class="infobox-label"><a href="/x">Elevation</a></th>'
               '<td class="infobox-data">8,848.86&#160;m (29,031.7&#160;ft)<sup>note</sup></td></tr><tr><th scope="row" class="infobox-label">Prominence</th><td>8,849 m</td></tr>')

    def test_parse_infobox_value(self):
        self.assertEqual(tasks.parse_infobox_value(self.INFOBOX), '8848.86')
        self.assertEqual(tasks.parse_infobox_value(self.INFOBOX, 'Prominence'), '8849')
        self.assertIsNone(tasks.parse_infobox_value(self.INFOBOX, 'Nope'))

    def test_wikipedia_truth_with_fake_fetch(self):
        self.assertEqual(tasks.wikipedia_truth(fetch=lambda url: json.dumps({'parse': {'text': self.INFOBOX}})), '8848.86')
        with self.assertRaises(RuntimeError):
            tasks.wikipedia_truth(fetch=lambda url: json.dumps({'parse': {'text': '<p>none</p>'}}))

    def test_android_truth_uses_getprop(self):
        seen = []

        def fake(argv, **_):
            seen.append(argv)
            return type('R', (), {'stdout': '15\n'})()
        self.assertEqual(tasks.android_truth(sh=fake, serial='emulator-5554'), '15')
        self.assertEqual(seen[0], ['adb', '-s', 'emulator-5554', 'shell', 'getprop', 'ro.build.version.release'])

    def test_ios_truth_from_simctl_runtime(self):
        data = {'devices': {'com.apple.CoreSimulator.SimRuntime.iOS-26-5': [{'udid': 'U1'}], 'com.apple.CoreSimulator.SimRuntime.iOS-26-2': [{'udid': 'U2'}]}}
        fake = lambda argv, **_: type('R', (), {'stdout': json.dumps(data)})()
        self.assertEqual(tasks.ios_truth('U1', sh=fake), '26.5')
        with self.assertRaises(RuntimeError):
            tasks.ios_truth('U3', sh=fake)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events = Path(self.tmp.name) / 'events.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def test_pages_render_and_log_roundtrip(self):
        for route in ('booking', 'orders', 'form', 'upload', 'shop', 'product/a', 'product/b', 'product/c'):
            status, ctype, body = server.handle_get('/%s?run=r1' % route, self.events)
            self.assertEqual(status, 200, route)
            self.assertIn(b'r1', body)
        self.assertEqual(server.handle_get('/nope', self.events)[0], 404)
        server.handle_get('/log?run=r1&task=form&action=submit&id=intake&v_name=Dana', self.events)
        rows = server.read_events(self.events, 'r1')
        self.assertEqual(rows[0]['values'], {'name': 'Dana'})

    def test_upload_post_logs_filename_size_hash(self):
        data = b'hello world'
        boundary = 'XBOUNDARY'
        body = (b'--XBOUNDARY\r\nContent-Disposition: form-data; name="attachment"; filename="a b.txt"\r\nContent-Type: text/plain\r\n\r\n' + data + b'\r\n--XBOUNDARY--\r\n')
        status, _, _ = server.handle_post('/upload?run=r2&task=upload', 'multipart/form-data; boundary=' + boundary, body, self.events)
        self.assertEqual(status, 200)
        row = server.read_events(self.events, 'r2')[0]
        self.assertEqual(row['values'], {'filename': 'a b.txt', 'size': '11', 'sha256': hashlib.sha256(data).hexdigest()})
        self.assertEqual(server.handle_post('/upload?run=r2', 'multipart/form-data; boundary=B', b'--B--\r\n', self.events)[0], 400)

    def test_loopback_only(self):
        httpd = server.make_server(0, self.events)
        try:
            self.assertEqual(httpd.server_address[0], '127.0.0.1')
        finally:
            httpd.server_close()

    def test_compare_pages_show_price_and_stock_only_on_product_pages(self):
        shop = server.handle_get('/shop?run=x', self.events)[2].decode()
        self.assertNotIn('$', shop)
        self.assertIn('Out of stock', server.handle_get('/product/b?run=x', self.events)[2].decode())
        self.assertIn('$36.75', server.handle_get('/product/c?run=x', self.events)[2].decode())


class PromptAndRunnerTest(unittest.TestCase):
    FACTS = {'url': 'http://127.0.0.1:1/x?run=r', 'title': 'T r', 'file': '/tmp/f.txt', 'app': 'Calculator', 'device': 'DEV'}
    LEAKS = ['Quillon', '36.75', 's10', '1044', '1316', '8,848', '8848', 'Telehealth', 'getprop', 'look', 'cua_do', 'computer-use', 'cua-driver']

    def test_no_answers_decoys_or_tool_hints_in_any_prompt(self):
        for task in tasks.ORDER:
            for arm in runner.ARMS:
                prompt = runner.build_prompt(task, arm, self.FACTS)
                for leak in self.LEAKS:
                    if leak == '1316' and task == 'calculator':
                        continue
                    self.assertNotIn(leak.lower(), prompt.lower().replace('looks', ''), '%s/%s leaks %r' % (task, arm, leak))

    def test_calculator_prompt_states_expression_not_result(self):
        self.assertIn('47 x 28', runner.build_prompt('calculator', 'native', self.FACTS))
        self.assertNotIn('1316', runner.build_prompt('calculator', 'native', self.FACTS))

    def test_upload_prompt_carries_the_path(self):
        self.assertIn('/tmp/f.txt', runner.build_prompt('upload', 'native', self.FACTS))

    def test_each_arm_sees_exactly_one_mcp_server_strictly(self):
        with tempfile.TemporaryDirectory() as tmp:
            for arm, server_name in runner.ARM_SERVER.items():
                cfg = runner.mcp_config(arm, tmp)
                self.assertEqual(list(json.loads(cfg.read_text())['mcpServers']), [server_name])
                argv = runner.claude_argv(arm, 'p', 'claude-sonnet-5-5', 60, cfg)
                self.assertIn('--strict-mcp-config', argv)
                self.assertEqual(argv[argv.index('--allowedTools') + 1], 'mcp__' + server_name)
                self.assertEqual(argv[argv.index('--model') + 1], 'claude-sonnet-5-5')
                self.assertEqual(argv[argv.index('--max-turns') + 1], '60')
                denied = argv[argv.index('--disallowedTools') + 1].split(',')
                self.assertIn('Bash', denied)
        self.assertIn('Skill', runner.DISALLOWED['native'])

    def test_native_arm_launches_cua_driver_mcp_and_cu_arm_the_facade_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = json.loads(runner.mcp_config('native', tmp).read_text())['mcpServers']['cua-driver']
            self.assertTrue(native['command'].endswith('/.local/bin/cua-driver'))
            self.assertEqual(native['args'], ['mcp'])
            cu = json.loads(runner.mcp_config('computer-use', tmp).read_text())['mcpServers']['computer-use-oh']
            self.assertTrue(cu['args'][0].endswith('computer_use/server.py'))

    def test_server_key_is_not_the_reserved_computer_use_name(self):
        self.assertNotIn('computer-use', runner.ARM_SERVER.values())

    def test_refuses_without_consent(self):
        with self.assertRaises(SystemExit) as cm:
            runner.main(['--tasks', 'booking'])
        self.assertIn('--i-have-consent', str(cm.exception))

    def test_plan_needs_no_consent_and_has_no_side_effects(self):
        self.assertEqual(runner.main(['--plan']), 0)

    def test_native_browser_is_chrome_for_testing_with_throwaway_profile(self):
        argv = surfaces.chrome_argv('/x/Google Chrome for Testing', '/tmp/prof', 'http://127.0.0.1:1/', {'x': 3000, 'y': 0, 'width': 1920, 'height': 1080})
        self.assertIn('--window-position=3040,40', argv)  # inside the agent display, never the user's screen
        self.assertTrue(any(a == '--user-data-dir=/tmp/prof' for a in argv))
        self.assertNotIn('Google Chrome.app', ' '.join(argv))

    def test_emulator_window_only_for_native(self):
        self.assertIn('-no-window', surfaces.emulator_argv('androidnaa-api35', headless=True))
        self.assertNotIn('-no-window', surfaces.emulator_argv('androidnaa-api35', headless=False))
        self.assertEqual(surfaces.emulator_argv('androidnaa-api35', True)[1:3], ['-avd', 'androidnaa-api35'])

    def test_process_diff_only_reports_new_and_killable_subset(self):
        before = [(1, '/x/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')]
        after = before + [(2, '/y/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing --user-data-dir=/t'), (3, '/Applications/Simulator.app/Contents/MacOS/Simulator')]
        new = surfaces.new_processes(before, after)
        self.assertEqual([p for p, _ in new], [2, 3])
        self.assertEqual([p for p, _ in surfaces.killable(new)], [2])  # a Simulator the user opened is reported, never killed

    def test_upload_file_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = surfaces.prepare_upload_file(tmp)
            self.assertEqual(info['size'], tasks.UPLOAD_SIZE)
            self.assertEqual(info['sha256'], hashlib.sha256(Path(info['path']).read_bytes()).hexdigest())


class ScoreTest(unittest.TestCase):
    def write_transcript(self, path, text, cost=0.5):
        lines = [
            {'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'tool_use', 'name': 'mcp__computer-use__look', 'input': {}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': [{'type': 'image', 'source': {'type': 'base64', 'data': 'A' * 50000}}]}]}},
            {'type': 'assistant', 'message': {'id': 'm2', 'content': [{'type': 'text', 'text': text}]}},
            {'type': 'result', 'num_turns': 2, 'total_cost_usd': cost, 'duration_ms': 4000, 'result': text, 'is_error': False, 'subtype': 'success',
             'usage': {'input_tokens': 10, 'output_tokens': 20, 'cache_read_input_tokens': 30, 'cache_creation_input_tokens': 40}},
        ]
        Path(path).write_text('\n'.join(json.dumps(x) for x in lines) + '\nnot json\n')

    def test_sanitize_drops_base64_and_caps_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp) / 'raw', Path(tmp) / 'out'
            self.write_transcript(raw, 'x' * 9000)
            score.sanitize_file(raw, out)
            body = out.read_text()
            self.assertNotIn('AAAAAAAA', body)
            self.assertIn('omitted_bytes', body)
            self.assertIn('chars cut', body)
            for line in body.splitlines():
                json.loads(line)

    def test_scan_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_transcript(Path(tmp) / 't', 'It shows 1,316.')
            t = score.scan_transcript(Path(tmp) / 't')
            self.assertEqual((t['turns'], t['mcp_calls'], t['cost_usd']), (2, 1, 0.5))
            self.assertEqual(t['tokens'], {'input': 10, 'output': 20, 'cache_read': 30, 'cache_write': 40})
            self.assertEqual(t['final_text'], 'It shows 1,316.')

    def test_score_run_end_to_end_with_fake_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.write_transcript(base / 'c.jsonl', 'The display shows 1,316')
            (base / 'c.monitor.jsonl').write_text(
                json.dumps({'t': 1.0, 'kind': 'focus_change', 'from_app': 'Terminal', 'to_app': 'Calculator', 'steal': True}) + '\n')
            run = {'run_id': 'r1', 'arm': 'native', 'task': 'calculator', 'truth': '1316', 'wall_s': 12.0, 'returncode': 0,
                   'transcript': 'c.jsonl', 'timeline': 'c.monitor.jsonl',
                   'monitor': {'focus_steals': 1, 'new_user_windows': 0, 'cursor_px': 0, 'cursor_bursts': 0, 'monitor_ok': True}}
            row = score.score_run(run, base / 'events.jsonl', base)
            self.assertEqual(row['outcome'], 'correct')
            self.assertEqual((row['turns'], row['interruptions']['focus_steals']), (2, 1))
            self.assertIn('Calculator took focus from Terminal', row['annoyances'][0])
            self.assertIn('| calculator | native | correct |', score.table([row]))

    def test_timeout_without_acting_is_timeout_not_wrong(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 't.jsonl').write_text('')
            run = {'run_id': 'r2', 'arm': 'native', 'task': 'booking', 'returncode': 'timeout', 'transcript': 't.jsonl'}
            self.assertEqual(score.score_run(run, base / 'none.jsonl', base)['outcome'], 'timeout')


class _FakeDisplay:
    def __init__(self, rect, park_moves=True):
        self._rect, self.park_moves, self.parked = rect, park_moves, []
        self.client = self
        self.windows = None

    def inside(self, b):
        r = self._rect
        return bool(b) and r['x'] <= b['x'] and r['y'] <= b['y'] and b['x'] + b['width'] <= r['x'] + r['width'] and b['y'] + b['height'] <= r['y'] + r['height']

    def park(self, wid):
        if not self.park_moves:
            raise RuntimeError('window was not moved')
        self.parked.append(wid)
        for w in self.windows:
            if w['window_id'] == wid:
                w['bounds'] = {'x': self._rect['x'] + 10, 'y': 10, 'width': 400, 'height': 300}


class ParkTest(unittest.TestCase):
    RECT = {'x': 3000, 'y': 0, 'width': 1920, 'height': 1080}

    def run_park(self, windows, park_moves=True, match=lambda w: w['app_name'] == 'Calculator'):
        ad = _FakeDisplay(self.RECT, park_moves)
        ad.windows = windows
        clock = iter(range(0, 1000)).__next__
        return ad, surfaces.park_windows(match, timeout=5, list_windows=lambda: [dict(w) for w in ad.windows], display=ad,
                                         sleep=lambda s: None, clock=clock)

    def win(self, x, app='Calculator', wid=7):
        return {'window_id': wid, 'app_name': app, 'layer': 0, 'pid': 1, 'bounds': {'x': x, 'y': 50, 'width': 400, 'height': 300}}

    def test_parks_and_verifies(self):
        ad, parked = self.run_park([self.win(100)])
        self.assertEqual(parked, [7])

    def test_already_on_agent_display_needs_no_park(self):
        ad, parked = self.run_park([self.win(3100)])
        self.assertEqual(parked, [])

    def test_park_failure_refuses_instead_of_leaving_window_on_user_screen(self):
        with self.assertRaises(surfaces.SetupRefused):
            self.run_park([self.win(100)], park_moves=False)

    def test_no_window_refuses(self):
        with self.assertRaises(surfaces.SetupRefused):
            self.run_park([self.win(100, app='Zoom')])

    def test_user_windows_never_parked(self):
        ad, _ = self.run_park([self.win(100), self.win(200, app='Slack', wid=9)])
        self.assertEqual(ad.parked, [7])


class SafetyTest(unittest.TestCase):
    def test_foreign_facade_detected(self):
        rows = [(10, '/x/.venv-facade/bin/python /x/computer_use/server.py'), (11, '/c/space-mover display serve --width 1920'),
                (12, 'npm exec @mobilenext/mobile-mcp@1.0.6'), (13, '/Applications/Zoom.app/Contents/MacOS/zoom.us')]
        self.assertEqual([p for p, _ in surfaces.foreign_facades(rows, own={11})], [10, 12])

    def test_harness_display_is_not_a_stray(self):
        rows = [(5, '/c/space-mover display serve'), (6, '/y/Google Chrome for Testing.app/x')]
        self.assertEqual([p for p, _ in surfaces.killable(rows, own={5})], [6])

    def test_page_token_hides_the_arm(self):
        for rid in ('native-booking-1', 'computer-use-booking-1'):
            tok = runner.page_token(rid)
            self.assertNotIn('native', tok)
            self.assertNotIn('computer', tok)
        self.assertNotEqual(runner.page_token('native-booking-1'), runner.page_token('computer-use-booking-1'))

    def test_web_prompts_name_no_arm(self):
        facts = {'url': 'http://127.0.0.1:1/booking?run=r123', 'title': 'Clinic Slots r123'}
        for arm in runner.ARMS:
            self.assertNotIn('native', runner.build_prompt('booking', arm, facts).lower().replace('natively', ''))
            self.assertNotIn('computer-use', runner.build_prompt('booking', arm, facts))

    def test_ios_prompt_names_the_app_actually_opened(self):
        self.assertIn('Simulator app', runner.build_prompt('ios', 'native', {'device': 'U', 'app': 'Simulator'}))
        self.assertIn('Device Hub', runner.build_prompt('ios', 'native', {'device': 'U', 'app': 'Device Hub'}))

    def test_agent_cannot_use_shell_like_builtins(self):
        for arm in runner.ARMS:
            for tool in ('Bash', 'Monitor', 'CronCreate', 'RemoteTrigger'):
                self.assertIn(tool, runner.DISALLOWED[arm])


class LabelTest(unittest.TestCase):
    def test_acted_without_answer_is_failed_not_no_action(self):
        self.assertEqual(tasks.judge('calculator', text='', truth='1316', acted=True)[0], 'failed')
        self.assertEqual(tasks.judge('calculator', text='', truth='1316', acted=False)[0], 'no-action')
        self.assertEqual(tasks.judge('calculator', text='', truth='1316', acted=True, timed_out=True)[0], 'timeout')

    def test_events_acted_without_events_is_failed(self):
        self.assertEqual(tasks.judge('booking', events=[], acted=True)[0], 'failed')
        self.assertEqual(tasks.judge('booking', events=[], acted=False)[0], 'no-action')

    def test_declined_report_is_failed_even_if_a_number_matches(self):
        text = "I couldn't get the Android version. The device is androidnaa-api35 on API 15 or so; I never reached Settings."
        out, detail = tasks.judge('android', text=text, truth='15', acted=True)
        self.assertEqual(out, 'failed')
        self.assertTrue(detail['declined'])
        self.assertEqual(tasks.judge('ios', text='I could not open Settings.', truth='26.5', acted=True)[0], 'failed')
        self.assertEqual(tasks.judge('ios', text='The simulator runs iOS 26.5.', truth='26.5', acted=True)[0], 'correct')

    def test_compare_reports_strict_and_relaxed(self):
        out, detail = tasks.judge('compare', text='Quillon Arc Lamp, $36.75\n(Marlow Banker Lamp at $29.00 is out of stock)',
                                  truth=fx.COMPARE_ANSWER, acted=True)
        self.assertEqual((out, detail['strict']), ('correct', 'wrong'))
        out, detail = tasks.judge('compare', text='Quillon Arc Lamp, $36.75', truth=fx.COMPARE_ANSWER, acted=True)
        self.assertEqual((out, detail['strict']), ('correct', 'correct'))

    def test_missing_truth_is_unscored_not_wrong(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / 't.jsonl').write_text(json.dumps({'type': 'assistant', 'message': {'id': 'm', 'content': [{'type': 'tool_use', 'id': 'u', 'name': 'mcp__x__y'}]}}) + '\n'
                                          + json.dumps({'type': 'result', 'result': 'It runs Android 15', 'num_turns': 2}) + '\n')
            for run in ({'truth': None}, {'truth': None, 'truth_error': 'RuntimeError: adb getprop returned nothing'}):
                rec = dict(run, run_id='x', arm='native', task='android', transcript='t.jsonl')
                self.assertEqual(score.score_run(rec, base / 'events.jsonl', base)['outcome'], 'unscored')

    def test_events_are_looked_up_by_page_token(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / 't.jsonl').write_text(json.dumps({'type': 'result', 'result': 'booked', 'num_turns': 1}) + '\n')
            (base / 'events.jsonl').write_text(json.dumps({'ts': 1, 'run': 'rtok', 'action': 'book', 'id': fx.BOOKING_EXPECTED_ID}) + '\n')
            rec = {'run_id': 'native-booking-1', 'page_run': 'rtok', 'arm': 'native', 'task': 'booking', 'transcript': 't.jsonl'}
            self.assertEqual(score.score_run(rec, base / 'events.jsonl', base)['outcome'], 'correct')

    def test_device_hub_is_attributed(self):
        tl = [{'kind': 'focus_change', 'to_app': 'Device Hub', 't': 1}, {'kind': 'new_user_window', 'app': 'qemu-system-aarch64', 't': 2}]
        self.assertEqual(score.attributed(tl)['agent_focus_steals'], 1)
        self.assertEqual(score.attributed(tl)['agent_windows_on_user_screens'], 1)


if __name__ == '__main__':
    unittest.main()
