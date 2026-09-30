"""The agent browser (#60, CE-FACADE-009): the default target of goto / open_tab / read_pages. Fakes only: no download, no launch, no desktop.

The Driver, the process launcher, the installer and the spaces client are fakes; the browser tools are test_browser.BrowserDriver
(shapes measured live on 0.31.0). Each test names the wrong patch it fails.
"""
import tempfile
import unittest
from pathlib import Path

import test_browser as tb
from agent_browser import AgentBrowser, INSTALL_ARGV
from agent_display import AgentDisplay
from core import Facade
from test_agent_display import FakeSpaces, Unavailable

AGENT_PID, AGENT_WIN = 4242, 77
DISPLAY = {'x': -1920, 'y': 0, 'width': 1920, 'height': 1080}
ON_DISPLAY = {'x': -1880.0, 'y': 40.0, 'width': 1840.0, 'height': 1000.0}
ON_USER_SCREEN = {'x': 40.0, 'y': 45.0, 'width': 1600.0, 'height': 1000.0}


class FakeProc:
    def __init__(self, pid):
        self.pid, self.dead, self.terminated = pid, False, False
    def poll(self):return 0 if self.dead else None
    def terminate(self):self.terminated = self.dead = True
    def wait(self, timeout=None):return 0
    def kill(self):self.dead = True


class World:
    """What is running: the launcher records every command; the window appears (or not) where the launch put it."""
    def __init__(self):
        self.commands, self.procs, self.bounds, self.appears = [], [], ON_DISPLAY, True
    def popen(self, argv, **kw):
        self.commands.append(argv)
        if any(not p.dead for p in self.procs):self.appears = True  # a second launch on a live profile forwards to it: a new window appears
        proc = FakeProc(AGENT_PID if not self.procs else AGENT_PID + len(self.procs))
        self.procs.append(proc)
        return proc
    def agent_windows(self):
        live = [p for p in self.procs if not p.dead]
        if not (self.appears and live):return []
        return [{'app_name': 'Google Chrome for Testing', 'pid': live[0].pid, 'window_id': AGENT_WIN, 'title': 'about:blank', 'is_on_screen': True, 'layer': 0, 'bounds': self.bounds}]


class AgentDriver(tb.BrowserDriver):
    def __init__(self, world):
        super().__init__();self.world = world
    def call(self, tool, args, timeout=20):
        if tool == 'list_windows':
            return {'windows': [{'pid': 1, 'window_id': 2, 'title': 'Demo', 'app_name': 'Google Chrome', 'is_on_screen': True, 'layer': 0,
                                 'bounds': ON_USER_SCREEN}, *self.world.agent_windows()]}
        return super().call(tool, args, timeout)


class Base(unittest.TestCase):
    def make(self, mode='auto', display_fail=None, display_mode='auto', installed=True, npx=True, install_ok=True, bounds=None):
        self.cache = Path(tempfile.mkdtemp())
        self.world = World()
        if bounds:self.world.bounds = bounds
        self.installs = []
        if installed:
            exe = self.cache / 'browsers' / 'chrome' / 'mac_arm-1' / 'chrome-mac-arm64' / 'Google Chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing'
            exe.parent.mkdir(parents=True);exe.write_text('')
        def run(command, **kw):
            self.installs.append(command)
            if install_ok:
                exe = self.cache / 'browsers' / 'chrome' / 'mac_arm-1' / 'chrome-mac-arm64' / 'Google Chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing'
                exe.parent.mkdir(parents=True, exist_ok=True);exe.write_text('')
            return type('R', (), {'returncode': 0 if install_ok else 1, 'stdout': '', 'stderr': ''})()
        self.log = [];self.spaces = FakeSpaces(self.log, display_fail)
        self.agent = AgentDisplay(mode=display_mode, apps=[], client=self.spaces, sleep=lambda s: None)
        self.ab = AgentBrowser(mode=mode, cache=self.cache, popen=self.world.popen, run=run, sleep=lambda s: None, which=(lambda n: '/bin/npx') if npx else (lambda n: None))
        self.driver = AgentDriver(self.world)
        self.f = Facade(self.driver, sleep=lambda s: None, agent_display=self.agent, agent_browser=self.ab)
        return self.f
    def go(self, *steps):
        return self.f.do('Open the page', title='Demo', expect=None, steps=list(steps))
    def bound_pids(self):
        return {a['pid'] for a in self.driver.called('get_browser_state') if 'pid' in a}


GOTO = {'do': 'goto', 'url': tb.BOOKING}


class Target(Base):
    def test_goto_defaults_to_the_agent_browser_not_the_users_window(self):
        # Wrong patch: navigate the window the caller named (the user's Chrome) by default.
        self.make()
        r = self.go(GOTO)
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertEqual(self.bound_pids(), {AGENT_PID})
        self.assertEqual(len(self.world.commands), 1)

    def test_profile_user_routes_to_the_users_chrome_and_launches_nothing(self):
        # Wrong patch: ignore profile and always use the agent browser (the user's logged-in pages become unreachable).
        self.make()
        self.go({**GOTO, 'profile': 'user'})
        self.assertEqual(self.bound_pids(), {1})
        self.assertEqual(self.world.commands, [])

    def test_the_user_mode_setting_restores_the_old_default(self):
        self.make(mode='user')
        self.go(GOTO)
        self.assertEqual((self.bound_pids(), self.world.commands), ({1}, []))

    def test_an_explicit_agent_profile_overrides_the_user_mode_default(self):
        self.make(mode='user')
        self.go({**GOTO, 'profile': 'agent'})
        self.assertEqual(self.bound_pids(), {AGENT_PID})

    def test_a_bad_profile_value_is_refused_before_anything_starts(self):
        self.make()
        r = self.go({**GOTO, 'profile': 'shared'})
        self.assertEqual(r['status'], 'refused')
        self.assertEqual(self.world.commands, [])


class Launch(Base):
    def test_the_launch_places_the_window_on_the_agent_display(self):
        # Wrong patch: launch without a position (a flash on the user's screen), or compute it from the main display.
        self.make()
        self.go(GOTO)
        argv = self.world.commands[0]
        self.assertIn('--window-position=-1880,40', argv)
        self.assertIn('--window-size=1840,1000', argv)
        self.assertIn('--user-data-dir=%s' % (self.cache / 'agent-profile'), argv, 'a profile folder we own')
        self.assertIn('--remote-debugging-port=0', argv)
        self.assertEqual(self.spaces.parked, [], 'already inside the display: nothing to move')

    def test_a_window_that_opened_on_the_users_screen_is_parked(self):
        # Wrong patch: trust the launch flags (the coordinator measured a wrong position): verify the bounds, park if outside.
        self.make(bounds=ON_USER_SCREEN)
        self.go(GOTO)
        self.assertEqual(self.spaces.parked, [AGENT_WIN])

    def test_without_a_display_it_launches_normally_and_reports_it(self):
        # Wrong patch: refuse or crash in auto when the helper is missing.
        self.make(display_fail=Unavailable('no helper'))
        r = self.go(GOTO)
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertFalse([a for a in self.world.commands[0] if a.startswith('--window-position')])
        self.assertIn('agent_display: unavailable', r['agent_display_note'])

    def test_required_refuses_before_launching_anything(self):
        # Wrong patch: launch first, then find out the display is missing (a window on the user's screen).
        self.make(display_fail=Unavailable('no helper'), display_mode='required')
        r = self.go(GOTO)
        self.assertEqual((r['status'], r['steps'][0]['reason']), ('refused', 'agent_display_unavailable'))
        self.assertEqual(self.world.commands, [])
        self.assertEqual(self.driver.called('get_browser_state'), [])

    def test_a_window_that_never_appears_is_a_typed_refusal_and_the_process_is_stopped(self):
        self.make()
        self.world.appears = False
        self.f.sleep = lambda s: None
        ticks = iter(range(0, 10000, 5))
        self.ab.clock = lambda: next(ticks)
        r = self.go(GOTO)
        self.assertEqual((r['status'], r['steps'][0]['reason']), ('refused', 'agent_browser_unavailable'))
        self.assertTrue(self.world.procs[0].terminated)


class Reuse(Base):
    def test_consecutive_calls_reuse_one_window(self):
        # Wrong patch: launch (or open a window) per call: the user watches windows pile up.
        self.make()
        self.go(GOTO);self.go({'do': 'open_tab', 'url': tb.BOOKING});self.go({'do': 'open_tab', 'url': tb.BOOKING})
        self.assertEqual(len(self.world.commands), 1)
        self.assertEqual(self.bound_pids(), {AGENT_PID})
        self.assertEqual(self.ab.window_id, AGENT_WIN)

    def test_a_dead_browser_is_started_again_once(self):
        self.make()
        self.go(GOTO);self.world.procs[0].dead = True
        self.go(GOTO);self.go(GOTO)
        self.assertEqual(len(self.world.commands), 2)

    def test_a_closed_window_of_a_live_browser_gets_one_new_window_not_a_new_browser(self):
        self.make()
        self.go(GOTO)
        self.world.appears = False  # the user closed the agent window; the process lives
        self.go(GOTO);self.go(GOTO)
        self.assertEqual(len(self.world.commands), 2)
        self.assertEqual(len([p for p in self.world.procs if not p.dead]), 2, 'the forwarded launch is not adopted as the browser')
        self.assertEqual(self.ab.proc, self.world.procs[0])

    def test_shutdown_stops_the_browser_and_the_display(self):
        self.make()
        self.go(GOTO)
        self.f.shutdown()
        self.assertTrue(self.world.procs[0].terminated)
        self.assertIn(('stop',), self.log)


class Install(Base):
    def test_an_installed_browser_is_used_without_downloading(self):
        self.make(installed=True)
        self.go(GOTO)
        self.assertEqual(self.installs, [])

    def test_a_missing_browser_is_installed_into_our_folder_with_a_bounded_command(self):
        # Wrong patch: install into a system location, or without a bound.
        self.make(installed=False)
        self.go(GOTO)
        self.assertEqual(self.installs, [INSTALL_ARGV + ['--path', str(self.cache / 'browsers')]])
        self.assertEqual(len(self.world.commands), 1)

    def test_no_npx_is_a_typed_refusal_naming_the_command(self):
        # Wrong patch: crash, or fall back to the user's Chrome silently.
        self.make(installed=False, npx=False)
        r = self.go(GOTO)
        step = r['steps'][0]
        self.assertEqual((r['status'], step['reason']), ('refused', 'agent_browser_unavailable'))
        self.assertIn('npx -y @puppeteer/browsers install chrome@stable', step['message'])
        self.assertEqual((self.world.commands, self.driver.called('get_browser_state')), ([], []))

    def test_a_failed_download_is_a_typed_refusal(self):
        self.make(installed=False, install_ok=False)
        r = self.go(GOTO)
        self.assertEqual(r['steps'][0]['reason'], 'agent_browser_unavailable')
        self.assertEqual(self.world.commands, [])

    def test_a_configured_path_replaces_the_download(self):
        self.make(installed=False)
        exe = self.cache / 'my-chromium';exe.write_text('')
        self.ab.path = str(exe)
        self.go(GOTO)
        self.assertEqual((self.installs, self.world.commands[0][0]), ([], str(exe)))


class Surface(Base):
    def test_the_server_default_is_the_agent_browser(self):
        import server
        self.assertIsInstance(server.facade.agent_browser, AgentBrowser)
        self.assertEqual(server.facade.agent_browser.mode, 'auto')


if __name__ == '__main__':
    unittest.main()
