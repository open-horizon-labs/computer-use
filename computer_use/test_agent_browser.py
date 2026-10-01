"""The agent browser (#60, CE-FACADE-009): the default target of goto / open_tab / read_pages. Fakes only: no download, no launch, no desktop.

The Driver, the process launcher, the installer and the spaces client are fakes; the browser tools are test_browser.BrowserDriver
(shapes measured live on 0.31.0). Each test names the wrong patch it fails.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_browser as tb
from agent_browser import AgentBrowser, INSTALL_ARGV, placement_for, seed_window_placement
from agent_display import AgentDisplay
from core import Facade
from test_agent_display import FakeSpaces, Unavailable

AGENT_PID, AGENT_WIN = 4242, 77
DISPLAY = {'x': -1920, 'y': 0, 'width': 1920, 'height': 1080}
ON_DISPLAY = {'x': -1880.0, 'y': 40.0, 'width': 1840.0, 'height': 1000.0}
ON_USER_SCREEN = {'x': 40.0, 'y': 45.0, 'width': 1600.0, 'height': 1000.0}


class FakeProc:
    def __init__(self, pid, on_exit=None, hangs=False):
        self.pid, self.dead, self.terminated, self.killed, self.hangs, self.on_exit = pid, False, False, False, hangs, on_exit
    def poll(self):return 0 if self.dead else None
    def terminate(self):
        self.terminated = True
        if not self.hangs:self.exit()
    def exit(self):
        self.dead = True
        if self.on_exit:self.on_exit()  # Chrome writes its window placement back as it quits
    def wait(self, timeout=None):
        if self.hangs and not self.killed:raise subprocess.TimeoutExpired('chrome', timeout)
        return 0
    def kill(self):
        self.killed = True;self.exit()


class World:
    """What is running: the launcher records every command; the window appears (or not) where the launch put it."""
    def __init__(self):
        self.commands, self.procs, self.bounds, self.appears = [], [], ON_DISPLAY, True
        self.profile, self.prefs_at_launch, self.on_exit, self.hangs = None, [], None, False
    def popen(self, argv, **kw):
        self.commands.append(argv)
        prefs = Path(self.profile) / 'Default' / 'Preferences' if self.profile else None
        self.prefs_at_launch.append(json.loads(prefs.read_text()) if prefs and prefs.exists() else None)  # what Chrome would read as it starts
        if any(not p.dead for p in self.procs):self.appears = True  # a second launch on a live profile forwards to it: a new window appears
        proc = FakeProc(AGENT_PID if not self.procs else AGENT_PID + len(self.procs), self.on_exit, self.hangs)
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
        self.world = World();self.world.profile = self.cache / 'agent-profile'
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

    def test_without_a_display_nothing_is_launched_even_in_auto(self):
        # Wrong patch: launch normally when the helper is missing (auto): a window on the user's screen is never acceptable.
        self.make(display_fail=Unavailable('no helper'))
        r = self.go(GOTO)
        self.assertEqual((r['status'], r['steps'][0]['reason']), ('refused', 'agent_display_unavailable'))
        self.assertIn('nothing was opened', r['steps'][0]['message'])
        self.assertEqual(self.world.commands, [])
        self.assertFalse((self.cache / 'agent-profile' / 'Default' / 'Preferences').exists())
        self.assertEqual(self.driver.called('get_browser_state'), [])

    def test_an_explicit_off_is_the_only_way_to_launch_without_a_display(self):
        # Wrong patch: treat off like auto (refuse), or seed/verify against a display that does not exist.
        self.make(display_mode='off')
        r = self.go(GOTO)
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertFalse([a for a in self.world.commands[0] if a.startswith('--window-position')])
        self.assertFalse((self.cache / 'agent-profile' / 'Default' / 'Preferences').exists())

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


STALE = {'bottom': 1037, 'left': 10, 'maximized': False, 'right': 1610, 'top': 37,
         'work_area_bottom': 1119, 'work_area_left': 0, 'work_area_right': 1724, 'work_area_top': 37}


class Placement(Base):
    def test_the_placement_is_the_display_inset_by_40_on_its_work_area(self):
        # Wrong patch: inset the wrong way, mark maximized, or take the work area from the main display.
        self.assertEqual(placement_for(DISPLAY), {'left': -1880, 'top': 40, 'right': -40, 'bottom': 1040, 'maximized': False,
                                                  'work_area_left': -1920, 'work_area_top': 0, 'work_area_right': 0, 'work_area_bottom': 1080})

    def test_a_missing_file_is_created_with_the_placement(self):
        # Wrong patch: only edit an existing Preferences file (a fresh profile then restores nothing we chose).
        profile = Path(tempfile.mkdtemp())
        seed_window_placement(profile, DISPLAY)
        self.assertEqual(json.loads((profile / 'Default' / 'Preferences').read_text()), {'browser': {'window_placement': placement_for(DISPLAY)}})

    def test_every_other_preference_is_kept_and_the_stale_placement_replaced(self):
        # Wrong patch: overwrite the whole file, or merge so the stale (10,37) placement survives.
        profile = Path(tempfile.mkdtemp());(profile / 'Default').mkdir()
        (profile / 'Default' / 'Preferences').write_text(json.dumps({'homepage': 'x', 'browser': {'window_placement': STALE, 'theme': 3}, 'a': {'b': [1]}}))
        seed_window_placement(profile, DISPLAY)
        prefs = json.loads((profile / 'Default' / 'Preferences').read_text())
        self.assertEqual(prefs['browser']['window_placement'], placement_for(DISPLAY))
        self.assertEqual((prefs['homepage'], prefs['browser']['theme'], prefs['a']), ('x', 3, {'b': [1]}))

    def test_local_state_copies_are_removed_and_the_rest_of_it_kept(self):
        # Wrong patch: leave Local State alone (a copy there can override), or delete the file.
        profile = Path(tempfile.mkdtemp())
        (profile / 'Local State').write_text(json.dumps({'browser': {'window_placement': STALE, 'enabled_labs': ['x']}, 'other': {'window_placement': STALE}, 'keep': 1}))
        seed_window_placement(profile, DISPLAY)
        self.assertEqual(json.loads((profile / 'Local State').read_text()), {'browser': {'enabled_labs': ['x']}, 'other': {}, 'keep': 1})

    def test_a_corrupt_preferences_file_is_replaced_not_a_crash(self):
        profile = Path(tempfile.mkdtemp());(profile / 'Default').mkdir()
        (profile / 'Default' / 'Preferences').write_text('{not json')
        seed_window_placement(profile, DISPLAY)
        self.assertEqual(json.loads((profile / 'Default' / 'Preferences').read_text())['browser']['window_placement'], placement_for(DISPLAY))

    def test_the_placement_is_on_disk_before_chrome_starts(self):
        # Wrong patch: seed after popen (Chrome has already restored the stale placement), or seed in a profile Chrome does not use.
        self.make()
        prof = self.cache / 'agent-profile' / 'Default';prof.mkdir(parents=True)
        (prof / 'Preferences').write_text(json.dumps({'browser': {'window_placement': STALE}, 'keep': 1}))
        self.go(GOTO)
        seen = self.world.prefs_at_launch[0]
        self.assertEqual((seen['browser']['window_placement'], seen['keep']), (placement_for(DISPLAY), 1))
        self.assertIn('--window-position=-1880,40', self.world.commands[0], 'the flags stay too')

    def test_a_running_browser_is_reused_and_its_profile_is_not_touched(self):
        # Wrong patch: rewrite the placement (or launch) while our Chrome is running.
        self.make()
        self.go(GOTO)
        prefs = self.cache / 'agent-profile' / 'Default' / 'Preferences'
        prefs.write_text('{"browser": {"window_placement": %s}}' % json.dumps(STALE))
        self.go(GOTO)
        self.assertEqual((len(self.world.commands), json.loads(prefs.read_text())['browser']['window_placement']), (1, STALE))

    def test_the_rect_follows_the_displays_current_bounds_on_every_launch(self):
        # Wrong patch: remember the display's x from the first launch (the virtual display appears at a different x each time).
        self.make()
        self.go(GOTO)
        self.assertEqual(self.world.prefs_at_launch[0]['browser']['window_placement']['left'], -1880)
        self.world.procs[0].exit()
        moved = {'id': 6, 'x': 2087, 'y': 0, 'width': 1920, 'height': 1080}
        self.spaces.displays = lambda: [{'id': 1, 'x': 0, 'y': 0, 'width': 2087, 'height': 1355}, moved]
        self.world.bounds = {'x': 2127.0, 'y': 40.0, 'width': 1840.0, 'height': 1000.0}
        r = self.go(GOTO)
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertIn('--window-position=2127,40', self.world.commands[1])
        self.assertEqual(self.world.prefs_at_launch[1]['browser']['window_placement']['left'], 2127)
        self.assertEqual(self.world.prefs_at_launch[1]['browser']['window_placement']['work_area_left'], 2087)


class Containment(Base):
    def misplaced_run(self, bounds, **kw):
        self.make(**kw)
        self.world.bounds = bounds
        return self.go(GOTO)

    def test_a_window_on_the_users_screen_is_quit_and_refused_not_parked(self):
        # Wrong patch: rely on a park-after (AX may not list a fresh process's window), or leave the window up.
        r = self.misplaced_run(ON_USER_SCREEN)
        step = r['steps'][0]
        self.assertEqual((r['status'], step['reason']), ('refused', 'agent_browser_misplaced'))
        self.assertIn("'x': 40.0", step['message'])
        self.assertTrue(self.world.procs[0].terminated and self.world.procs[0].dead)
        self.assertEqual(self.spaces.parked, [])
        self.assertEqual(self.driver.called('get_browser_state'), [], 'nothing was bound or navigated')
        self.assertIsNone(self.ab.proc)

    def test_a_window_straddling_two_displays_is_refused_too(self):
        # Wrong patch: accept a window whose centre is inside the display (any overlap with another display is a refusal).
        r = self.misplaced_run({'x': -1000.0, 'y': 40.0, 'width': 1840.0, 'height': 1000.0})
        self.assertEqual(r['steps'][0]['reason'], 'agent_browser_misplaced')
        self.assertTrue(self.world.procs[0].dead)

    def test_a_window_with_no_bounds_cannot_be_verified_and_is_refused(self):
        # Wrong patch: treat unknown bounds as fine.
        r = self.misplaced_run(None)
        self.assertEqual(r['steps'][0]['reason'], 'agent_browser_misplaced')
        self.assertTrue(self.world.procs[0].dead)

    def test_the_saved_placement_is_deleted_even_when_chrome_writes_it_back_as_it_quits(self):
        # Wrong patch: delete the placement before the process has exited (Chrome saves the bad one on quit), or never delete it.
        self.make()
        prefs = self.cache / 'agent-profile' / 'Default' / 'Preferences'
        self.world.on_exit = lambda: prefs.write_text(json.dumps({'browser': {'window_placement': STALE}, 'keep': 1}))
        self.world.bounds = ON_USER_SCREEN
        self.go(GOTO)
        saved = json.loads(prefs.read_text())
        self.assertNotIn('window_placement', saved['browser'])
        self.assertEqual(saved['keep'], 1)

    def test_a_process_that_ignores_sigterm_is_killed(self):
        # Wrong patch: terminate and never escalate (the window stays up).
        self.make()
        self.world.hangs = True
        self.world.bounds = ON_USER_SCREEN
        self.go(GOTO)
        self.assertTrue(self.world.procs[0].terminated and self.world.procs[0].killed)

    def test_a_window_inside_the_display_is_accepted_and_nothing_is_killed(self):
        # Wrong patch: refuse every launch, or kill a good one.
        self.make()
        r = self.go(GOTO)
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertFalse(self.world.procs[0].terminated)
        self.assertEqual(self.spaces.parked, [])
        prefs = json.loads((self.cache / 'agent-profile' / 'Default' / 'Preferences').read_text())
        self.assertEqual(prefs['browser']['window_placement'], placement_for(DISPLAY))

    def test_a_created_window_straddling_the_display_is_parked_not_trusted(self):
        # Wrong patch: the centre-inside check for windows the facade creates (it overlaps the user's screen).
        self.make()
        self.agent.rect()
        self.f.window_created(5, 'Fresh', {'x': -1000.0, 'y': 40.0, 'width': 1840.0, 'height': 1000.0})
        self.assertEqual(self.spaces.parked, [5])


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
