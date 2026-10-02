"""#64 / CE-FACADE-010: agent onboarding. The user being onboarded is an LLM agent driving look and do.

Fakes only (no network, no desktop, no Driver, no skips): the doctor checks of cli.py run against test_cli.fake_env, the Facade against the captured
booking tree and the fake browser/mobile Drivers of the sibling tests. Each test names the tempting wrong patch it fails;
scripts/check_plan_mutations.py applies the ones listed there and requires the named tests to fail.
"""
import inspect
import json
import re
import unittest
from pathlib import Path

import agent_browser
import call_budget as cb
import cli
import look as lookmod
import mobile
import onboarding
import plan
import probe_fixture
import test_browser as tb
import test_live_shapes as lv
import test_mobile as tm
from core import DriverCallFailed, Facade
from test_cli import D, PERMS_OK, STATUS_UP, fake_env

HERE = Path(__file__).resolve().parent
BUDGET = cb.load_budget()
NODE_OK = {('node', '--version'): (0, 'v20.1.0', '')}
DAEMON_UP = {(D, 'status'): (0, STATUS_UP, '')}
GRANTED = {**DAEMON_UP, ('ps',): (0, 'cua-driver serve --grant existing-profile', ''), (D, 'permissions', 'status', '--json'): (0, PERMS_OK, '')}
NOT_GRANTED = {**DAEMON_UP, ('ps',): (0, 'cua-driver serve', ''), (D, 'permissions', 'status', '--json'): (0, json.dumps({'accessibility': True, 'screen_recording': False}), '')}
HEALTHY_BROWSER = dict(environ={'CUA_AGENT_BROWSER_PATH': '/ab/chrome'}, files=['/ab/chrome', '/sock'])


def checks(response):
    return [e['check'] for e in response.get('setup', [])]


class NoBrowser:
    """An agent browser that cannot start (what AgentBrowser.window raises when Chrome for Testing is missing and npx is too)."""
    mode = 'auto'

    def alive(self):
        return False

    def window(self, f):
        raise agent_browser.unavailable('Chrome for Testing is not installed and npx (Node.js) is missing')

    def stop(self):
        pass


class SetupBlock(unittest.TestCase):
    def facade(self, env, driver=None, **kw):
        return Facade(driver or tb.BrowserDriver(), sleep=lambda s: None, setup_env=lambda: env, **kw)

    def goto(self, f, **kw):
        return f.do('Open the booking page', expect=None, title='Demo', steps=[{'do': 'goto', 'url': tb.BOOKING, 'expect': 'Dr. Priya Shah'}], **kw)

    def test_a_browser_refusal_carries_only_the_browser_blockers_with_who(self):
        # Wrong patch: attach the whole doctor report (daemon, Perception, providers...) or nothing but the bare reason.
        env = fake_env(NOT_GRANTED, files=['/sock'])  # the machine has MORE wrong with it: no Node.js, a Driver without the grant, a missing screen grant
        r = self.goto(self.facade(env, agent_browser=NoBrowser()))
        self.assertEqual((r['status'], r['reason']), ('refused', 'agent_browser_unavailable'))
        self.assertEqual(checks(r), ['agent_browser', 'node'], r.get('setup'))
        by = {e['check']: e for e in r['setup']}
        self.assertEqual(by['agent_browser']['who'], 'agent')  # bootstrap installs Chrome for Testing
        self.assertEqual(by['node']['who'], 'user')  # installing Node.js is the user's
        for entry in r['setup']:
            self.assertEqual(set(entry), {'check', 'status', 'fix', 'who'})
            self.assertTrue(entry['fix'])
        self.assertNotIn('detail', json.dumps(r['setup']))

    def test_a_driver_grant_refusal_names_the_grant_and_who_can_give_it(self):
        # Wrong patch: tell the agent to run bootstrap for a System Settings grant it cannot give.
        d = tb.BrowserDriver()
        d.refuse = {'get_browser_state': 'browser_requires_setup', 'browser_prepare': 'existing_profile_not_granted'}
        r = self.goto(self.facade(fake_env(NOT_GRANTED, files=['/sock']), d))
        self.assertEqual(r['reason'], 'permission_required')
        by = {e['check']: e for e in r['setup']}
        self.assertEqual(sorted(by), ['driver.grant', 'driver.permissions'])
        self.assertEqual(by['driver.grant']['who'], 'agent')  # bootstrap restarts the daemon with --grant existing-profile
        self.assertEqual(by['driver.permissions']['who'], 'user')
        self.assertIn('System Settings', by['driver.permissions']['fix'])

    def test_a_grant_the_user_must_give_when_every_driver_check_passes(self):
        # Wrong patch: no setup at all when the daemon looks healthy (Full Disk Access cannot be read from outside and is the likely cause).
        d = tb.BrowserDriver()
        d.refuse = {'get_browser_state': 'browser_requires_setup', 'browser_prepare': 'existing_profile_not_granted'}
        r = self.goto(self.facade(fake_env(GRANTED, files=['/sock']), d))
        self.assertEqual(checks(r), ['driver.full_disk_access'])
        self.assertEqual(r['setup'][0]['who'], 'user')

    def test_a_device_refusal_carries_the_device_blocker_never_the_browser_ones(self):
        # Wrong patch: one flat blocker list for every refusal (the agent would be told to install Chrome for Testing because a phone is missing).
        stdio = mobile.StdioBackend(which=lambda exe: None, env={'PATH': ''})
        f = Facade(mobile=mobile.Mobile(stdio), sleep=lambda s: None, setup_env=lambda: fake_env(NOT_GRANTED, files=['/sock']))
        r = f.look(device=tm.EMULATOR)
        self.assertEqual(r['reason'], 'mobile_backend_unavailable')
        self.assertEqual(checks(r), ['node'])
        self.assertEqual(r['setup'][0]['who'], 'user')
        d = f.do('Tap', device=tm.EMULATOR, expect=None, steps=[{'do': 'press', 'control': 'Refresh connection', 'expect': None}])
        self.assertNotIn('setup', d)  # the same blocker set was already shown

    def test_a_device_list_with_the_backend_down_carries_the_blocker_too(self):
        stdio = mobile.StdioBackend(which=lambda exe: None, env={'PATH': ''})
        f = Facade(tb.BrowserDriver(), mobile=mobile.Mobile(stdio), sleep=lambda s: None, setup_env=lambda: fake_env())
        r = f.look(device='list')
        self.assertEqual(checks(r), ['node'])

    def test_a_missing_ios_device_agent_has_no_host_check_so_the_entry_is_fixed_and_names_the_user(self):
        backend = tm.overview_backend()
        backend.fail['mobile_list_elements_on_screen'] = (tm.FIX / 'ios_agent_missing.txt').read_text()
        f = Facade(mobile=mobile.Mobile(backend), sleep=lambda s: None, setup_env=lambda: fake_env(NODE_OK))
        r = f.look(device=tm.SIMULATOR)
        self.assertEqual(r['reason'], 'mobile_device_agent_missing')
        self.assertEqual(checks(r), ['mobile.device_agent'])
        self.assertEqual(r['setup'][0]['who'], 'user')

    def test_perception_the_display_and_the_daemon_each_map_to_their_own_checks(self):
        # Wrong patch: map every reason to the Driver daemon check.
        perception = Facade(sleep=lambda s: None, setup_env=lambda: fake_env({(D, 'extension', 'status', 'cua-perception', '--json'): (0, json.dumps({'installed': False}), '')}))
        r = perception.mark({'status': 'refused', 'reason': 'perception_not_available', 'steps': []}, 'do')
        self.assertEqual((checks(r), r['setup'][0]['who']), (['perception'], 'agent'))
        display = Facade(sleep=lambda s: None, setup_env=lambda: fake_env())
        r = display.mark({'status': 'refused', 'reason': 'agent_display_unavailable', 'steps': []}, 'do')
        self.assertEqual(checks(r), ['space_mover.built'])
        down = Facade(sleep=lambda s: None, setup_env=lambda: fake_env())
        r = down.mark({'status': 'failed', 'reason': 'driver_call_failed', 'retryable': True}, 'look')
        self.assertEqual(checks(r), ['driver.installed', 'driver.daemon'])

    def test_a_failed_look_with_the_daemon_down_names_the_daemon_and_with_it_up_adds_nothing(self):
        class Dead:
            def call(self, tool, args, timeout=20):
                raise DriverCallFailed('driver_call_failed: list_windows exited 1', tool, 'exit')
        up = Facade(Dead(), sleep=lambda s: None, setup_env=lambda: fake_env({(D, '--version'): (0, 'cua-driver 0.31.0', ''), **DAEMON_UP}, files=['/sock']))
        r = up.look(title='Demo')
        self.assertEqual(r['reason'], 'driver_call_failed')
        self.assertNotIn('setup', r)  # a transient failure on a healthy daemon is a retry, not a setup problem
        down = Facade(Dead(), sleep=lambda s: None, setup_env=lambda: fake_env())
        r = down.look(title='Demo')
        self.assertEqual(checks(r), ['driver.installed', 'driver.daemon'])
        self.assertIn('once more', r['hint'])
        self.assertIn('Do not loop', r['hint'])

    def test_never_on_a_healthy_machine(self):
        # Wrong patch: attach the block whenever a blocking reason appears, without asking whether a check is really failing.
        env = fake_env({**NODE_OK, **GRANTED}, **HEALTHY_BROWSER)
        f = self.facade(env)
        r = f.mark({'status': 'refused', 'reason': 'agent_browser_unavailable', 'steps': []}, 'do')  # the browser started badly, but the host is fine
        self.assertNotIn('setup', r)
        self.assertEqual(f.setup_seen, set())

    def test_no_environment_reason_means_the_checks_are_never_run(self):
        # Wrong patch: run doctor on every refusal (a no_matching_record answer would cost subprocesses and show unrelated blockers).
        env = fake_env()
        f = self.facade(env, tb.BrowserDriver())
        r = f.do('x', expect=None, title='Demo', look_id='lk_0000000000', steps=[{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'x'}]}, 'expect': None}])
        self.assertEqual(r['status'], 'refused')
        self.assertNotIn('setup', r)
        self.assertEqual(env.calls, [])

    def test_once_per_blocker_set_and_again_when_the_set_changes(self):
        # Wrong patch: repeat the block on every refusal (noise), or never show it again after the first time even when the blockers changed.
        state = {'env': fake_env(NOT_GRANTED, files=['/sock'])}
        f = Facade(tb.BrowserDriver(), sleep=lambda s: None, setup_env=lambda: state['env'], agent_browser=NoBrowser())
        first = self.goto(f)
        second = self.goto(f)
        self.assertEqual(checks(first), ['agent_browser', 'node'])
        self.assertNotIn('setup', second)
        self.assertEqual(second['reason'], 'agent_browser_unavailable')  # the refusal itself is unchanged
        state['env'] = fake_env({**NODE_OK, **NOT_GRANTED}, files=['/sock'])  # the user installed Node.js: the blocker set is now just the browser
        third = self.goto(f)
        self.assertEqual(checks(third), ['agent_browser'])
        self.assertNotIn('setup', self.goto(f))

    def test_the_block_is_small_and_the_response_stays_under_the_byte_bound(self):
        # Wrong patch: attach every detail (checks, details, full fix texts) and push a refusal over max_response_bytes.
        env = fake_env(NOT_GRANTED, files=['/sock'])
        r = self.goto(self.facade(env, agent_browser=NoBrowser()))
        self.assertLessEqual(len(r['setup']), onboarding.MAX_ENTRIES)
        self.assertTrue(all(len(e['fix']) <= onboarding.MAX_FIX_CHARS for e in r['setup']))
        self.assertLess(len(json.dumps(r)), BUDGET['max_response_bytes']['value'])

    def test_the_facade_without_a_setup_env_never_attaches_and_the_server_passes_one(self):
        # Wrong patch: build a real cli.Env inside every Facade (every existing offline test would run the machine's cua-driver).
        r = self.goto(Facade(tb.BrowserDriver(), sleep=lambda s: None, agent_browser=NoBrowser()))
        self.assertEqual(r['reason'], 'agent_browser_unavailable')
        self.assertNotIn('setup', r)
        source = (HERE / 'server.py').read_text()
        self.assertRegex(source, r'facade=Facade\([^\n]*setup_env=')

    def test_a_setup_block_is_traced_content_free(self):
        f = self.facade(fake_env(NOT_GRANTED, files=['/sock']), agent_browser=NoBrowser())
        self.goto(f)
        shown = [e for e in f.events if e['operation'] == 'setup_shown']
        self.assertEqual(shown, [{'operation': 'setup_shown', 'checks': ['agent_browser', 'node']}])


class EmptyStates(unittest.TestCase):
    def test_no_devices_says_what_would_appear_and_the_one_call(self):
        # Wrong patch: keep the bare "pass device=<an id from devices>" hint when the list is empty.
        backend = tm.overview_backend()
        backend.fail['mobile_list_available_devices'] = '{"devices":[]}'
        f = Facade(tb.BrowserDriver(), mobile=mobile.Mobile(backend), sleep=lambda s: None)
        r = f.look(device='list')
        self.assertEqual((r['status'], r['devices']), ('ok', []))
        for part in ('{id, platform, name}', 'emulator -avd', 'xcrun simctl boot', 'look` with device="list" again'):
            self.assertIn(part, r['hint'])

    def test_a_listed_device_keeps_the_short_hint_and_a_down_backend_says_who_and_the_retry_rule(self):
        listed = Facade(tb.BrowserDriver(), mobile=mobile.Mobile(tm.overview_backend()), sleep=lambda s: None).look(device='list')
        self.assertEqual(listed['hint'], mobile.DISCOVERY_HINTS['listed'])
        down = Facade(tb.BrowserDriver(), mobile=mobile.Mobile(mobile.StdioBackend(which=lambda exe: None, env={'PATH': ''})), sleep=lambda s: None).look(device='list')
        self.assertIn('tell the user', down['hint'])
        self.assertIn('do not retry', down['hint'])

    def test_windows_without_an_agent_browser_says_how_to_start_it(self):
        # Wrong patch: an empty browser section with no next call.
        class Stopped:
            mode, alive = 'auto', lambda self: False
        f = Facade(tb.BrowserDriver(), sleep=lambda s: None, agent_browser=Stopped())
        notes = onboarding.windows_notes(f, {'windows': [{'title': 'Demo'}]})
        self.assertFalse(notes['agent_browser']['running'])
        self.assertIn('goto step', notes['agent_browser']['hint'])
        self.assertNotIn('windows_hint', notes)
        class Running:
            mode, alive = 'auto', lambda self: True
        self.assertEqual(onboarding.windows_notes(Facade(sleep=lambda s: None, agent_browser=Running()), {'windows': [{'title': 'x'}]}), {})
        user_mode = type('U', (), {'mode': 'user', 'alive': lambda self: False})()
        self.assertEqual(onboarding.windows_notes(Facade(sleep=lambda s: None, agent_browser=user_mode), {'windows': [{'title': 'x'}]}), {})

    def test_no_windows_names_the_grant_and_who_and_a_title_miss_says_how_to_list(self):
        f = Facade(sleep=lambda s: None)
        empty = onboarding.windows_notes(f, {'windows': []})
        self.assertIn('only the user can grant', empty['windows_hint'])
        self.assertIn('call `windows` again', empty['windows_hint'])
        self.assertIn('without title', onboarding.windows_notes(f, {'windows': []}, 'Nope')['windows_hint'])

    def test_the_advanced_windows_tool_merges_the_notes(self):
        # Wrong patch: compute the notes but return the bare window list from the tool.
        ran = cb.advanced_run(
            "import asyncio, json, server, call_budget as cb\n"
            "from core import Facade\nfrom test_core import FakeDriver\nfrom agent_browser import AgentBrowser\n"
            "server.facade = Facade(FakeDriver(), agent_browser=AgentBrowser(mode='auto'))\n"
            "out = json.loads(cb.result_text(asyncio.run(server.mcp.call_tool('windows', {}))))\n"
            "print(json.dumps({'keys': sorted(out), 'running': out.get('agent_browser', {}).get('running')}))")
        self.assertIn('agent_browser', ran['keys'])
        self.assertIs(ran['running'], False)

    def test_a_canvas_look_without_perception_names_the_installer_and_the_retry(self):
        import test_do as fx
        d = fx.FlatDriver()
        real = d.observe
        def canvas(*a):
            x = real(*a)
            x['elements'] = [e for e in x['elements'] if e['element_index'] == 0]
            return x
        d.observe = canvas
        r = Facade(d, sleep=lambda s: None).look(title='Demo')
        note = ' '.join(r['notes'])
        self.assertIn('install_perception.py', note)
        self.assertIn('call `look` again', note)

    def test_the_no_permission_hint_names_who_and_the_retry_rule(self):
        # Wrong patch: "call look to see the page" for a refusal only the user can clear.
        text = plan.hint_for('permission_required', 1, False)
        self.assertIn('ask the user', text)
        self.assertIn('Never reroute', text)
        self.assertNotIn('Call look to see', text)


def reasons_in(source):
    """Typed reasons raised by a module: 'reason: message' passed to Gap/_gap/MobileGap."""
    out = set()
    for line in source.splitlines():
        if re.search(r'(?<![A-Za-z])(Gap|_gap|MobileGap|CoreGap)\(', line) and 'class ' not in line:
            out.update(re.findall(r"""['"]([a-z][a-z0-9_]{3,}):""", line))
    return out


SOURCES = ('core', 'plan', 'browser', 'mobile', 'agent_browser', 'agent_display', 'menu', 'look', 'dom')
# Raised through a format string the scanner cannot read, or returned as a reason without a Gap: still reach responses.
REACH_ALSO = {'foreground_required', 'window_not_found', 'window_ambiguous', 'driver_call_failed', 'provider_failure', 'budget_exceeded', 'permission_required',
              'agent_browser_unavailable', 'agent_display_unavailable', 'mobile_backend_unavailable', 'mobile_device_agent_missing'}
STOP_AND_ASK = {'window_ax_unresolved', 'no_actionable_controls', 'mobile_backend_unavailable', 'mobile_device_agent_missing'}  # nothing a call can change: say who and the retry rule
CALL_NAMES = {name for name in (set(inspect.signature(__import__('server').do).parameters) | set(inspect.signature(__import__('server').look).parameters)
                                | set(__import__('server').PlanStep.model_fields) | set(__import__('server').StepWhere.model_fields))}
GENERIC = {'do', 'text', 'goal', 'lines', 'pid'}


def names_a_call(text):
    """The hint names the default tools or a parameter of them (as call text, never a primitive)."""
    if re.search(r'\b[Cc]all\s+`?(?:look|do)\b', text) or re.search(r'`(?:look|do)`', text):
        return True
    for name in CALL_NAMES - GENERIC:
        if '_' in name and re.search(r'\b%s\b' % name, text):
            return True
        if re.search(r'\b%s=' % name, text) or re.search(r'\b(?:Set|set|Give|give|Pass|pass) %s\b' % name, text):
            return True
    return False


def dedicated(reason):
    return plan.HINTS.get(reason) or mobile.DEVICE_HINTS.get(reason)


class HintCatalog(unittest.TestCase):
    def reasons(self):
        found = set(REACH_ALSO)
        for name in SOURCES:
            found |= reasons_in((HERE / (name + '.py')).read_text())
        return found

    def test_every_refusal_reason_that_reaches_a_response_has_its_own_hint(self):
        # Wrong patch: let a new refusal fall to the generic "call look to see the page" (permission_required once did).
        missing = sorted(r for r in self.reasons() if not dedicated(r))
        self.assertEqual(missing, [], 'add a hint naming look, do or a parameter (plan.HINTS, or mobile.DEVICE_HINTS for a device reason)')

    def test_every_hint_names_an_existing_tool_or_parameter_or_says_who_and_the_retry_rule(self):
        # Wrong patch: a hint that only restates the reason ("the menu item is disabled. Report it.").
        for table in (plan.HINTS, mobile.DEVICE_HINTS):
            for reason, text in table.items():
                if reason in STOP_AND_ASK:
                    self.assertIn('user', text, reason)
                    self.assertRegex(text, r'do not retry|Do not retry', reason)
                else:
                    self.assertTrue(names_a_call(text), '%s: %s' % (reason, text))

    def test_a_generic_fallback_still_names_the_next_call(self):
        self.assertTrue(names_a_call(plan.GENERIC_HINT))
        self.assertTrue(names_a_call(plan.hint_for('some_reason_nobody_wrote_a_hint_for', 3, False)))

    def test_the_tool_and_parameter_names_the_hints_use_exist(self):
        # Wrong patch: a hint that names a parameter do does not take (it would send the agent to a field the schema rejects).
        for table in (plan.HINTS, mobile.DEVICE_HINTS, mobile.DISCOVERY_HINTS):
            for reason, text in table.items():
                for token in re.findall(r'\b([a-z][a-z_]+)=', text):
                    self.assertIn(token, CALL_NAMES | {'devices', 'who'}, '%s names %s=' % (reason, token))
                for kind in re.findall(r'\{do:"([a-z_]+)"', text):
                    self.assertIn(kind, plan.DO_KINDS, reason)

    def test_no_hint_names_a_primitive_or_carries_page_text(self):
        for table in (plan.HINTS, mobile.DEVICE_HINTS, mobile.DISCOVERY_HINTS):
            for reason, text in table.items():
                self.assertIsNone(lookmod.PRIMITIVE_NAMES.search(text), reason)
        self.assertIsNone(lookmod.PRIMITIVE_NAMES.search(onboarding.NO_AGENT_BROWSER))  # the windows notes name `windows` itself: they answer that Advanced tool

    def test_the_scanner_sees_a_new_reason(self):
        # Wrong patch: a scan that matches nothing, so the catalog test passes vacuously.
        self.assertEqual(reasons_in("raise Gap('brand_new_reason: it broke')\nx = _gap(\"other_new: y\")"), {'brand_new_reason', 'other_new'})
        self.assertGreaterEqual(len(self.reasons()), 40)
        self.assertIn('login_wall', self.reasons())

    def test_a_validation_refusal_uses_the_catalog_hint(self):
        r = Facade(tb.BrowserDriver(), sleep=lambda s: None).do('x', expect=None, title='Demo', steps=[{'do': 'press', 'control': 'Go'}, {'do': 'verify', 'expect': 'y'}])
        self.assertEqual(r['status'], 'refused')
        self.assertEqual(r['hint'], plan.HINTS[r['reason']] % {'n': 1})


class WelcomeScreen(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.text = server.INSTRUCTIONS

    def test_the_instructions_are_the_welcome_screen_not_the_manual(self):
        # Wrong patch: paste the whole tool description back into the instructions (they were three times this long).
        self.assertIs(self.server.mcp.instructions, self.text)
        self.assertLess(len(self.text), 2300)
        for part in ('look', 'do', '`expect`', 'look_id', 'The expect is the proof', 'who=user', 'never reroute', 'context_id'):
            self.assertIn(part, self.text, part)
        self.assertLess(self.text.index('`look`'), self.text.index('`do`'))
        self.assertFalse(lv.PRIMITIVES.search(self.text))

    def test_one_worked_example_goto_then_look_then_do(self):
        example = self.text.split('Example:', 1)[1].split('\n', 1)[0]
        order = [example.index(x) for x in ('goto', 'look(title', 'do(goal="Book', 'where:', 'expect:"Booked:"')]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.text.count('Example:'), 1)

    def test_the_detail_moved_to_the_tool_descriptions(self):
        # Wrong patch: delete the paragraphs from the instructions and from the docstrings too.
        docs = {name: doc for name, doc, _ in cb.tool_surface(cb.SERVER.read_text())}
        for part in ('CUA_AGENT_DISPLAY=off|auto|required', 'REFUSALS AND SETUP', 'setup=[{check, status, fix, who}]', 'profile="user"', 'read_pages'):
            self.assertIn(part, docs['do'], part)
            self.assertNotIn(part, self.text, part)
        self.assertIn('device="list"', docs['look'])

    def test_no_notice_is_repeated_beyond_the_untrusted_text_one(self):
        # Wrong patch: add a "remember: look first" notice to every response (the notice is a safety property; nothing else repeats).
        f = Facade(tb.BrowserDriver(), sleep=lambda s: None)
        r = f.look(title='Demo')
        self.assertEqual({k for k in r if 'notice' in k or k.startswith('reminder')}, {'notice'})
        self.assertTrue(r['untrusted_page_text'])


class FirstVerifiedDo(lv.LiveBase):
    def setUp(self):
        super().setUp()
        self.driver.script = lv.booked()
        self.clock_now = [100.0]
        self.f.clock = lambda: self.clock_now[0]
        self.f.started_at = 90.0
        self.look = self.f.look(title='Demo')
        self.conds, _ = cb.look_conditions(self.look, ['Dr. Morgan Reyes', 'Follow-up', '1:45 PM'])

    def press(self, **kw):
        return self.f.do('Book the slot', expect=None, title='Demo', look_id=self.look['look_id'], steps=[{'do': 'press', 'where': {'lines': self.conds}, 'expect': 'Booked:'}], **kw)

    def test_the_first_done_do_records_calls_and_seconds_since_start(self):
        # Wrong patch: count only do calls (the look is an LLM-visible call), or time from the first call instead of from the server start.
        self.clock_now[0] = 112.5
        r = self.press()
        self.assertEqual(r['status'], 'done')
        self.assertEqual(self.f.first_do, {'calls': 2, 'seconds': 22.5})
        self.assertEqual([e for e in self.f.events if e['operation'] == 'time_to_first_verified_do'], [{'operation': 'time_to_first_verified_do', 'calls': 2, 'seconds': 22.5}])
        self.assertEqual(self.f.close()['time_to_first_verified_do'], {'calls': 2, 'seconds': 22.5})

    def test_it_is_recorded_once(self):
        # Wrong patch: overwrite on every done do (the metric would drift to the last call).
        self.press()
        before = dict(self.f.first_do)
        self.driver.executed.clear()
        self.clock_now[0] = 500.0
        self.press()
        self.assertEqual(self.f.first_do, before)
        self.assertEqual(len([e for e in self.f.events if e['operation'] == 'time_to_first_verified_do']), 1)

    def test_a_goto_or_a_verify_alone_is_not_the_aha_moment(self):
        # Wrong patch: any done status counts (a goto lands a page; it proves nothing was done on it).
        f = Facade(tb.BrowserDriver(), sleep=lambda s: None)
        r = f.do('Open it', expect=None, title='Demo', steps=[{'do': 'goto', 'url': tb.BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done')
        self.assertIsNone(f.first_do)
        v = self.f.do('Check', expect=None, title='Demo', steps=[{'do': 'verify', 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(v['status'], 'observed')
        self.assertIsNone(self.f.first_do)

    def test_a_refused_or_stopped_do_is_not_recorded(self):
        r = self.f.do('Book', expect=None, title='Demo', look_id=self.look['look_id'], steps=[{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'nobody'}]}, 'expect': 'Booked:'}])
        self.assertNotEqual(r['status'], 'done')
        self.assertIsNone(self.f.first_do)

    def test_the_single_form_do_counts_when_it_is_done_and_verified(self):
        r = self.f.do('Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM', title='Demo', expect='Booked:',
                      records={'fields': lv.BOOKING_FIELDS, 'predicates': lv.BOOKING_ONE})
        self.assertEqual(r['status'], 'done')
        self.assertEqual(self.f.first_do['calls'], 2)

    def test_the_budget_scenarios_tie_the_trace_to_the_counted_calls(self):
        # Wrong patch: budget a number the trace does not show (table() flags a first_do_calls that differs from the counted calls).
        measured = cb.measure_scenarios()
        self.assertEqual(measured['onboarding_first_do']['calls'], 2)
        self.assertEqual(measured['onboarding_first_do_goto']['calls'], 3)
        self.assertEqual((measured['onboarding_first_do']['first_do_calls'], measured['onboarding_first_do_goto']['first_do_calls']), (2, 3))
        for name, calls in (('onboarding_first_do', 2), ('onboarding_first_do_goto', 3)):
            s = BUDGET['scenarios'][name]
            self.assertEqual((s['max_llm_visible_calls']['value'], s['max_reader_calls']['value'], s['max_chooser_calls']['value']), (calls, 0, 0))
            self.assertEqual(s['max_llm_visible_calls']['changed_by'], 'CE-FACADE-010')
        skewed = {**measured, 'onboarding_first_do': {**measured['onboarding_first_do'], 'first_do_calls': 5}}
        self.assertTrue(any('time_to_first_verified_do traced 5 calls' in p for p in cb.table(BUDGET, skewed)[1]))
        self.assertEqual(cb.budget_violations(), [])
        self.assertEqual(BUDGET['scenarios']['plan_booking_look_do']['max_llm_visible_calls']['value'], 2)  # existing numbers do not move
        self.assertEqual(BUDGET['scenarios']['nav_goto_look_plan']['max_llm_visible_calls']['value'], 3)


class FirstCallNeedsNoTitle(unittest.TestCase):
    """The first do on a fresh machine has no window to name: goto on the agent browser opens it and the answer's summary.title names it."""
    class Window:
        mode = 'auto'
        def alive(self): return True
        def window(self, f): return 1, 2
        def stop(self): pass

    def facade(self, browser=None):
        d = tb.BrowserDriver()
        return Facade(d, sleep=lambda s: None, agent_browser=browser), d

    GOTO = {'do': 'goto', 'url': tb.BOOKING, 'expect': 'Dr. Priya Shah'}

    def test_a_goto_first_plan_on_the_agent_browser_needs_no_title_and_answers_with_one(self):
        # Wrong patch: keep demanding a title for a window that does not exist yet (the worked example in the instructions would be refused).
        f, d = self.facade(self.Window())
        r = f.do('Open the booking page', expect=None, steps=[self.GOTO])
        self.assertEqual(r['status'], 'done', r)
        self.assertTrue(r['summary']['title'])
        self.assertEqual(d.called('browser_navigate')[0]['url'], tb.BOOKING)

    def named(self, d):
        """A real Driver's window list: the agent browser's window (1, 2) and its title."""
        real = d.call
        d.call = lambda tool, args, timeout=20: ({'windows': [{'pid': 1, 'window_id': 2, 'title': 'Clinic Slots dbg20'}]} if tool == 'list_windows' else real(tool, args, timeout))

    def test_a_titleless_goto_without_expect_answers_with_the_window_title_and_a_navigation_hint(self):
        # Wrong patch (live 2026-09-30, #64): summary only when an observation was taken, so the unverified answer had no title; the hint spoke of a click.
        f, d = self.facade(self.Window())
        self.named(d)
        r = f.do('Open the booking page', expect=None, steps=[{'do': 'goto', 'url': tb.BOOKING, 'expect': None}])
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertEqual(r['summary']['title'], 'Clinic Slots dbg20')
        self.assertEqual(r['summary']['window'], {'pid': 1, 'window_id': 2})
        self.assertEqual(r['steps'][0]['page']['url'], tb.BOOKING)
        self.assertIn('look(title="Clinic Slots dbg20")', r['hint'])
        self.assertNotIn('click', r['hint'].lower())

    def test_a_titleless_goto_that_stops_still_names_the_window(self):
        f, d = self.facade(self.Window())
        self.named(d)
        d.landed = {'url': 'https://ads.example/promo', 'title': 'Promo'}
        r = f.do('Open the booking page', expect=None, steps=[self.GOTO])
        self.assertEqual(r['steps'][0]['reason'], 'navigated_elsewhere', r)
        self.assertEqual(r['summary']['title'], 'Clinic Slots dbg20')

    def test_a_goto_with_a_title_given_also_answers_with_summary_title(self):
        # Wrong patch: add summary only on done.
        f, d = self.facade(self.Window())
        self.named(d)
        r = f.do('x', expect=None, title='Demo', steps=[{'do': 'goto', 'url': tb.BOOKING, 'expect': None}])
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertTrue(r['summary']['title'])
        self.assertNotIn('click', r['hint'].lower())

    def test_everything_else_still_names_its_window(self):
        # Wrong patch: drop the title requirement for every plan (a press or a user-profile goto would act on no named window).
        f, _ = self.facade(self.Window())
        for steps in ([{'do': 'press', 'control': 'Book', 'expect': None}], [{**self.GOTO, 'profile': 'user'}]):
            r = f.do('x', expect=None, steps=steps)
            self.assertEqual((r['status'], r.get('reason')), ('refused', 'bad_request'), steps)
        none, _ = self.facade(None)  # no agent browser configured: goto uses the user's window, which must be named
        self.assertEqual(none.do('x', expect=None, steps=[self.GOTO]).get('reason'), 'bad_request')
        user_mode = type('U', (), {'mode': 'user', 'alive': lambda self: False})()
        self.assertEqual(self.facade(user_mode)[0].do('x', expect=None, steps=[self.GOTO]).get('reason'), 'bad_request')


class FakeHttpd:
    def __init__(self):
        self.stopped = []

    def shutdown(self):
        self.stopped.append('shutdown')

    def server_close(self):
        self.stopped.append('close')


class ScriptedFacade:
    """What check_first_do_probe needs of a Facade: do, look, first_do, shutdown, with scripted answers."""
    def __init__(self, answers, first_do=None, crash=None):
        self.answers, self.first_do, self.crash, self.calls = list(answers), first_do, crash, []

    def _next(self, name, kw):
        self.calls.append((name, kw))
        if self.crash:
            raise self.crash
        return self.answers.pop(0)

    def do(self, goal, **kw):
        return self._next('do', kw)

    def look(self, **kw):
        return self._next('look', kw)

    def shutdown(self):
        pass


class Probe(unittest.TestCase):
    URL = 'http://127.0.0.1:1/booking'

    def serve(self):
        self.httpd = FakeHttpd()
        return lambda: (self.httpd, self.URL)

    def test_the_real_facade_reaches_ready_through_goto_look_do(self):
        # Wrong patch: a probe that only checks the pieces (the server answers, the daemon runs) and never runs one look and one verified do.
        d = tb.BrowserDriver()
        d.script = lv.booked()
        real_call = d.call
        d.call = lambda tool, args, timeout=20: ({'windows': [{'pid': 1, 'window_id': 2, 'title': d.fix['window_title']}]} if tool == 'list_windows' else real_call(tool, args, timeout))  # the window list agrees with the page's own title, as a real Driver's does
        class Window:
            mode = 'auto'
            def alive(self): return True
            def window(self, f): return 1, 2
            def stop(self): pass
        f = Facade(d, sleep=lambda s: None, agent_browser=Window())
        r = cli.check_first_do_probe(fake_env(), facade=f, serve=self.serve())
        self.assertEqual((r['name'], r['status']), ('probe.first_verified_do', cli.OK), r)
        self.assertIn('first verified do after 3 calls', r['detail'])
        self.assertIn('time_to_first_verified_do', r['detail'])
        self.assertEqual(f.first_do['calls'], 3)
        self.assertEqual(d.called('browser_navigate')[0]['url'], self.URL)
        self.assertEqual(self.httpd.stopped, ['shutdown', 'close'])  # the fixture server is always stopped

    def test_a_refused_goto_reports_the_setup_fixes_and_still_stops_the_server(self):
        # Wrong patch: report only "probe failed" without the fix the setup block already computed.
        f = Facade(tb.BrowserDriver(), sleep=lambda s: None, agent_browser=NoBrowser(), setup_env=lambda: fake_env(NOT_GRANTED, files=['/sock']))
        r = cli.check_first_do_probe(fake_env(), facade=f, serve=self.serve())
        self.assertEqual(r['status'], cli.BLOCKER)
        self.assertIn('agent_browser_unavailable', r['detail'])
        self.assertIn('python -m computer_use bootstrap (agent)', r['fix'])
        self.assertEqual(self.httpd.stopped, ['shutdown', 'close'])

    def test_a_crash_is_a_result_not_a_traceback(self):
        r = cli.check_first_do_probe(fake_env(), facade=ScriptedFacade([], crash=RuntimeError('boom')), serve=self.serve())
        self.assertEqual(r['status'], cli.BLOCKER)
        self.assertEqual(r['detail'], 'probe failed: RuntimeError')
        self.assertEqual(self.httpd.stopped, ['shutdown', 'close'])

    def test_an_unverified_press_is_not_ready(self):
        # Wrong patch: report ready because the clicks were delivered.
        look = {'status': 'ok', 'look_id': 'lk_1', 'records': [{'r': 'r1', 'lines': ['Dr. Priya Shah', 'Intake']}]}
        f = ScriptedFacade([{'status': 'done', 'summary': {'title': 'Clinic Slots probe'}}, look, {'status': 'delivered_unverified', 'steps': []}])
        r = cli.check_first_do_probe(fake_env(), facade=f, serve=self.serve())
        self.assertEqual(r['status'], cli.BLOCKER)
        self.assertIn('did not finish', r['detail'])

    def test_a_non_unique_first_record_is_reported_not_guessed(self):
        look = {'status': 'ok', 'look_id': 'lk_1', 'records': [{'r': 'r1', 'lines': ['a']}, {'r': 'r2', 'lines': ['a', 'b']}]}
        f = ScriptedFacade([{'status': 'done', 'summary': {'title': 'T'}}, look])
        r = cli.check_first_do_probe(fake_env(), facade=f, serve=self.serve())
        self.assertIn('not unique', r['detail'])

    def test_doctor_probe_runs_the_first_do_probe_after_the_display_and_plain_doctor_does_not(self):
        ran = []
        def display(env):
            ran.append('display')
            return cli.result('space_mover.probe', cli.OK, 'ok')
        def first(env):
            ran.append('first_do')
            return cli.result(cli.PROBE_CHECK, cli.OK, 'ready')
        env = fake_env()
        plain = cli.run_checks(env)
        self.assertNotIn(cli.PROBE_CHECK, [r['name'] for r in plain])
        probed = cli.run_checks(env, probe=True, probes=(display, first))
        self.assertEqual(ran, ['display', 'first_do'])
        self.assertEqual(probed[-1]['name'], cli.PROBE_CHECK)

    def test_the_bundled_page_is_loopback_only_and_has_one_unique_record_per_slot(self):
        # Wrong patch: bind 0.0.0.0, or ship a page whose first record is not unique by its lines (the probe could not target it).
        httpd, url = probe_fixture.serve()
        try:
            self.assertEqual(httpd.server_address[0], '127.0.0.1')
            self.assertTrue(url.startswith('http://127.0.0.1:'))
        finally:
            httpd.shutdown()
            httpd.server_close()
        page = probe_fixture.render()
        self.assertEqual(page.count('>Book</button>'), len(probe_fixture.SLOTS))
        self.assertEqual(len({s[0] for s in probe_fixture.SLOTS}), len(probe_fixture.SLOTS))
        self.assertIn(probe_fixture.BOOKED, page)
        self.assertIn(probe_fixture.FIRST_PROVIDER, page)


if __name__ == '__main__':
    unittest.main()
