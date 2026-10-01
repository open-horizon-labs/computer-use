"""The agent browser (#60, CE-FACADE-009): the default target of goto / open_tab / read_pages. Fakes only: no download, no launch, no desktop.

The Driver, the process launcher, the installer and the spaces client are fakes; the browser tools are test_browser.BrowserDriver
(shapes measured live on 0.31.0). Each test names the wrong patch it fails.
"""
import json
import signal
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
        self.table, self.signals, self.order, self.popen_kw, self.helpers, self.deaf = [], [], [], [], 0, set()  # table: [pid, command, group, FakeProc|None]
    def add_process(self, pid, command, group=None, proc=None):
        self.table.append([pid, command, group, proc])
    def live(self):
        return [row for row in self.table if row[3] is None or not row[3].dead]
    def _drop(self, rows):
        for row in rows:
            if row[3] is not None and not row[3].dead:row[3].exit()
            if row in self.table:self.table.remove(row)
    def killpg(self, pgid, sig):
        rows = [r for r in self.live() if r[2] == pgid]
        if not rows:raise ProcessLookupError(pgid)
        if sig == 0:return
        self.signals.append(('killpg', pgid, sig))
        for r in rows:
            if r[3] is not None and sig == signal.SIGTERM:r[3].terminated = True
        if sig == signal.SIGKILL or (sig == signal.SIGTERM and not self.hangs and pgid not in self.deaf):
            for r in rows:
                if r[3] is not None and sig == signal.SIGKILL and not r[3].dead:r[3].killed = True
            self._drop(rows)
    def kill(self, pid, sig):
        rows = [r for r in self.live() if r[0] == pid]
        if not rows:raise ProcessLookupError(pid)
        self.signals.append(('kill', pid, sig))
        self.order.append(('kill', pid))
        if sig == signal.SIGKILL or pid not in self.deaf:self._drop(rows)
    def scan(self):
        return [(r[0], r[1]) for r in self.live()]
    def popen(self, argv, **kw):
        self.commands.append(argv);self.popen_kw.append(kw);self.order.append(('popen',))
        prefs = Path(self.profile) / 'Default' / 'Preferences' if self.profile else None
        self.prefs_at_launch.append(json.loads(prefs.read_text()) if prefs and prefs.exists() else None)  # what Chrome would read as it starts
        if any(not p.dead for p in self.procs):self.appears = True  # a second launch on a live profile forwards to it: a new window appears
        proc = FakeProc(AGENT_PID if not self.procs else AGENT_PID + len(self.procs), self.on_exit, self.hangs)
        self.procs.append(proc)
        self.add_process(proc.pid, ' '.join(str(a) for a in argv), proc.pid, proc)
        for i in range(self.helpers):  # Chrome's renderer/GPU helpers: same group, same user-data-dir on their command line
            self.add_process(proc.pid + 1000 + i, 'chrome --type=renderer --user-data-dir=%s' % self.profile, proc.pid)
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
        self.now = 0.0
        self.log = [];self.spaces = FakeSpaces(self.log, display_fail)
        self.agent = AgentDisplay(mode=display_mode, apps=[], client=self.spaces, sleep=lambda s: None)
        self.ab = AgentBrowser(mode=mode, cache=self.cache, popen=self.world.popen, run=run, sleep=self._sleep, clock=lambda: self.now, killpg=self.world.killpg, kill=self.world.kill, scan=self.world.scan, which=(lambda n: '/bin/npx') if npx else (lambda n: None))
        self.driver = AgentDriver(self.world)
        self.f = Facade(self.driver, sleep=lambda s: None, agent_display=self.agent, agent_browser=self.ab)
        return self.f
    def _sleep(self, seconds):
        self.now += seconds
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
        self.assertNotIn('browser', json.loads((self.cache / 'agent-profile' / 'Default' / 'Preferences').read_text()), 'no placement is seeded without a display')

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


STALE_CMD = 'Google Chrome for Testing --user-data-dir=%s --remote-debugging-port=0'


class Lifecycle(Base):
    def test_stop_kills_the_whole_group_and_helpers_outside_it(self):
        # Wrong patches: kill only the launched pid (helpers stay: 23 processes survived live); skip the survivor scan (a helper outside the group stays).
        self.make()
        self.world.helpers = 3
        self.go(GOTO)
        profile = str(self.cache / 'agent-profile')
        self.world.add_process(777, 'chrome --type=gpu --user-data-dir=%s' % profile)  # a helper that left the group
        self.world.add_process(778, 'chrome --user-data-dir=/somewhere/else')  # someone else's Chrome
        self.assertEqual(len(self.world.live()), 6)
        self.f.shutdown()
        self.assertEqual([r[0] for r in self.world.live()], [778], 'only the unrelated Chrome is left')
        self.assertIn(('killpg', AGENT_PID, signal.SIGTERM), self.world.signals)
        self.assertNotIn(('kill', 778, signal.SIGKILL), self.world.signals)
        self.assertIn(('kill', 777, signal.SIGKILL), self.world.signals)

    def test_stop_escalates_to_sigkill_on_the_group_after_three_seconds(self):
        # Wrong patch: SIGTERM only, or SIGKILL at once (no chance to flush), or wait without a bound.
        self.make()
        self.world.helpers = 2
        self.go(GOTO)
        self.world.hangs = True
        before = self.now
        self.ab.stop()
        self.assertEqual(self.world.live(), [])
        kinds = [sig for kind, pgid, sig in self.world.signals if kind == 'killpg' and pgid == AGENT_PID]
        self.assertEqual(kinds, [signal.SIGTERM, signal.SIGKILL])
        self.assertGreaterEqual(self.now - before, 3)
        self.assertLess(self.now - before, 4)

    def test_the_browser_is_launched_in_its_own_process_group_and_stop_runs_at_exit(self):
        # Wrong patch: share the server's group (killpg would take the server down), or no last-resort stop.
        import atexit
        registered = []
        original = atexit.register
        atexit.register = lambda fn, *a, **k: registered.append(fn)
        try:
            self.make()
            self.go(GOTO)
        finally:
            atexit.register = original
        self.assertIs(self.world.popen_kw[0].get('start_new_session'), True)
        self.assertEqual(self.ab.pgid, AGENT_PID)
        self.assertEqual(registered, [self.ab.stop])

    def test_a_stale_instance_is_killed_before_the_launch_and_logged(self):
        # Wrong patches: launch without looking (Chrome forwards into the stale instance and exits); kill it after the launch; kill silently.
        self.make()
        profile = str(self.cache / 'agent-profile')
        self.world.add_process(9001, STALE_CMD % profile)
        self.world.add_process(9002, 'chrome --type=renderer --user-data-dir=%s' % profile)
        self.go(GOTO)
        self.assertEqual(self.world.order[:3], [('kill', 9001), ('kill', 9002), ('popen',)])
        self.assertEqual([r[0] for r in self.world.live() if r[3] is None], [])
        events = [e for e in self.f.events if e['operation'] == 'agent_browser_recovered_stale']
        self.assertEqual(events[0]['pids'], [9001, 9002])

    def test_a_stale_instance_that_ignores_sigterm_is_killed_by_pid(self):
        # Wrong patch: SIGTERM and trust it.
        self.make()
        self.world.add_process(9001, STALE_CMD % (self.cache / 'agent-profile'))
        self.world.deaf.add(9001)
        self.go(GOTO)
        self.assertIn(('kill', 9001, signal.SIGKILL), self.world.signals)
        self.assertEqual(self.world.live()[0][0], AGENT_PID)

    def test_no_stale_instance_means_nothing_is_killed_and_nothing_logged(self):
        # Wrong patch: kill every Chrome, or log on every launch.
        self.make()
        self.world.add_process(500, 'chrome --user-data-dir=/not/ours')
        self.go(GOTO)
        self.assertEqual(self.world.signals, [])
        self.assertEqual([e for e in self.f.events if e['operation'] == 'agent_browser_recovered_stale'], [])


class Two(unittest.TestCase):
    """#91: two servers on one cache. A fake process table says who is alive (pid -> (start, command)); nothing is launched."""
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        exe = self.cache / 'browsers' / 'chrome' / 'mac_arm-1' / 'chrome-mac-arm64' / 'Google Chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing'
        exe.parent.mkdir(parents=True);exe.write_text('')
        self.world = World();self.world.profile = self.cache / 'agent-profile'
        self.alive = {100: ('Thu Oct  1 10:00:00 2026', 'python server.py'), 200: ('Thu Oct  1 10:05:00 2026', 'python server.py')}
        self.now = 0.0
        self.f = type('F', (), {'events': [], 'event': lambda me, name, **d: me.events.append((name, d))})()

    def server(self, pid):
        return AgentBrowser(mode='auto', cache=self.cache, popen=self.world.popen, sleep=lambda s: setattr(self, 'now', self.now + s), clock=lambda: self.now,
                            killpg=self.world.killpg, kill=self.world.kill, scan=self.world.scan, identify=lambda p: self.alive.get(p), getpid=lambda: pid)

    def launch(self, ab):
        ab._launch(None, self.f)
        return ab

    def names(self):
        return [e[0] for e in self.f.events]

    def test_a_second_server_never_kills_the_live_owners_browser_and_uses_its_own_profile(self):
        # Wrong patch: the old _recover_stale on the shared profile (SIGKILLed the live server's Chrome, issue #91).
        first, second = self.server(100), self.server(200)
        self.launch(first)
        owner_browser = first.proc.pid
        self.launch(second)
        self.assertEqual(self.world.signals, [], 'nothing was signalled')
        self.assertIn(owner_browser, [r[0] for r in self.world.live()])
        self.assertEqual(second.profile, self.cache / 'agent-profile-200')
        self.assertIn('--user-data-dir=%s' % (self.cache / 'agent-profile-200'), self.world.commands[-1])
        self.assertIn('agent_browser_separate_profile', self.names())
        second_browser = second.proc.pid
        first.stop()
        self.assertIn(second_browser, [r[0] for r in self.world.live()], 'the owner stopping does not touch the second server\'s browser')
        second.stop()
        self.assertFalse((self.cache / 'agent-profile-200').exists(), 'the per-server profile is removed at shutdown')

    def test_a_server_that_never_launched_kills_nothing_at_shutdown(self):
        # Wrong patch: stop() sweeps the shared profile even when another server owns it.
        first, idle = self.server(100), self.server(200)
        self.launch(first)
        idle.stop()
        self.assertEqual(self.world.signals, [])

    def test_a_dead_owner_is_recovered_and_the_lock_taken(self):
        # Wrong patch: treat any lock as live (never recover), or no lock taken.
        first, second = self.server(100), self.server(200)
        self.launch(first)
        stale = first.proc.pid
        del self.alive[100]
        self.launch(second)
        self.assertNotIn(stale, [r[0] for r in self.world.live()], 'the dead owner\'s browser was recovered')
        self.assertEqual(second.profile, second.base_profile)
        self.assertEqual(json.loads((second.profile / 'computer-use.owner').read_text())['pid'], 200)

    def test_a_reused_pid_is_not_a_live_owner(self):
        # Wrong patch: pid liveness alone (the OS gave the owner's pid to an unrelated process, or to another python server started later).
        first, second = self.server(100), self.server(200)
        self.launch(first)
        self.alive[100] = ('Fri Oct  2 09:00:00 2026', 'vim notes.txt')
        self.launch(second)
        self.assertEqual(second.profile, second.base_profile, 'the stale lock was recovered, not honoured')
        self.assertNotIn('agent_browser_separate_profile', self.names())
        # same command line but a different start time is still a reused pid
        (second.base_profile / 'computer-use.owner').write_text(json.dumps({'pid': 100, 'start': 'Thu Oct  1 10:00:00 2026', 'command': 'python server.py', 'browser_pid': 1}))
        self.alive[100] = ('Fri Oct  2 09:00:00 2026', 'python server.py')
        self.alive[300] = ('Fri Oct  2 09:10:00 2026', 'python server.py')
        third = self.launch(self.server(300))
        self.assertEqual(third.profile, third.base_profile)

    def test_stale_per_server_profiles_are_cleaned_at_the_next_launch_but_live_ones_are_kept(self):
        # Wrong patch: never clean them (they pile up), or clean every agent-profile-* (a live server's profile).
        dead, live = self.cache / 'agent-profile-999', self.cache / 'agent-profile-200'
        for d, pid in ((dead, 999), (live, 200)):
            d.mkdir()
            start, command = self.alive.get(pid, ('Wed Sep 30 08:00:00 2026', 'python server.py'))
            (d / 'computer-use.owner').write_text(json.dumps({'pid': pid, 'start': start, 'command': command}))
        self.launch(self.server(100))
        self.assertFalse(dead.exists())
        self.assertTrue(live.exists())

    def test_recovering_the_shared_profile_does_not_match_a_per_server_profile(self):
        # Wrong patch: substring match on the user-data-dir ('agent-profile' is a prefix of 'agent-profile-200').
        first = self.server(100)
        self.launch(first)
        del self.alive[100]
        self.world.add_process(5000, 'chrome --user-data-dir=%s --remote-debugging-port=0' % (self.cache / 'agent-profile-200'))
        self.alive[300] = ('x', 'y')
        self.launch(self.server(300))
        self.assertIn(5000, [r[0] for r in self.world.live()])


class NoRestore(Base):
    def test_preferences_are_seeded_so_no_session_is_restored(self):
        # Wrong patches: leave restore_on_startup unset (Chrome reopened the 6 tabs of the last run); drop other keys; seed after popen.
        self.make()
        prof = self.cache / 'agent-profile' / 'Default';prof.mkdir(parents=True)
        (prof / 'Preferences').write_text(json.dumps({'keep': 1, 'session': {'restore_on_startup': 1, 'other': 2}, 'profile': {'exit_type': 'Crashed', 'exited_cleanly': False, 'name': 'x'}}))
        self.go(GOTO)
        seen = self.world.prefs_at_launch[0]
        self.assertEqual(seen['session'], {'restore_on_startup': 5, 'other': 2})
        self.assertEqual(seen['profile'], {'exit_type': 'Normal', 'exited_cleanly': True, 'name': 'x'})
        self.assertEqual(seen['keep'], 1)

    def test_a_fresh_profile_gets_the_keys_too_and_the_flags_are_passed(self):
        # Wrong patch: seed only an existing file; omit the bubble flags.
        self.make()
        self.go(GOTO)
        seen = self.world.prefs_at_launch[0]
        self.assertEqual((seen['session']['restore_on_startup'], seen['profile']['exit_type'], seen['profile']['exited_cleanly']), (5, 'Normal', True))
        self.assertIn('--disable-session-crashed-bubble', self.world.commands[0])
        self.assertIn('--hide-crash-restore-bubble', self.world.commands[0])

    def test_session_files_are_deleted_and_cookies_and_storage_kept(self):
        # Wrong patches: keep the session files; delete the whole profile (logins lost); delete Session Storage.
        self.make()
        prof = self.cache / 'agent-profile' / 'Default';prof.mkdir(parents=True)
        (prof / 'Sessions').mkdir();(prof / 'Sessions' / 'Session_1').write_text('x')
        for name in ('Current Session', 'Last Session', 'Current Tabs', 'Last Tabs', 'Cookies', 'Login Data'):(prof / name).write_text('x')
        (prof / 'Local Storage').mkdir();(prof / 'Session Storage').mkdir()
        self.go(GOTO)
        for gone in ('Sessions', 'Current Session', 'Last Session', 'Current Tabs', 'Last Tabs'):
            self.assertFalse((prof / gone).exists(), gone)
        for kept in ('Cookies', 'Login Data', 'Local Storage', 'Session Storage'):
            self.assertTrue((prof / kept).exists(), kept)

    def test_a_running_browser_keeps_its_session_files(self):
        # Wrong patch: delete session files while our Chrome is running.
        self.make()
        self.go(GOTO)
        prof = self.cache / 'agent-profile' / 'Default'
        (prof / 'Current Session').write_text('live')
        self.go(GOTO)
        self.assertEqual((prof / 'Current Session').read_text(), 'live')


class NavigatedTab(Base):
    def three_tabs(self):
        self.driver.tabs = [{'url': 'https://a.example/', 'title': 'A', 'active': False},
                            {'url': 'https://b.example/', 'title': 'B', 'active': True},
                            {'url': 'https://c.example/', 'title': 'C', 'active': False}]

    def test_after_a_navigation_the_navigated_tab_is_the_tab_when_none_is_active(self):
        # Wrong patches: take the first (or last) tab; refuse browser_tab_ambiguous on every second goto; trust the remembered id (re-minted each bind).
        self.make()
        self.three_tabs()
        self.go(GOTO)
        self.assertEqual(self.driver.tabs[1]['title'], 'Booking')
        r = self.go({'do': 'goto', 'url': tb.BOOKING + '?again=1'})
        self.assertNotIn('browser_tab_ambiguous', json.dumps(r), r)
        last = [a for t, a in self.driver.browser_calls if t == 'browser_navigate'][-1]
        self.assertEqual(self.driver.minted[last['tab_id']], 1, 'the tab we navigated, not the first or last')

    def test_a_remembered_tab_that_cannot_be_told_apart_is_still_refused(self):
        # Wrong patch: guess when two tabs match the remembered url and title.
        self.make()
        self.three_tabs()
        self.go(GOTO)
        self.driver.tabs[0].update(url=self.driver.tabs[1]['url'], title=self.driver.tabs[1]['title'])
        r = self.go(GOTO)
        self.assertIn('browser_tab_ambiguous', json.dumps(r), r)
        self.assertEqual(len(self.driver.tabs), 3, 'no tab was closed')

    def test_the_memory_does_not_apply_to_other_browsers(self):
        # Wrong patch: apply the remembered tab to the user's own browser window (pid 1).
        from browser import remembered_tab
        self.make()
        self.three_tabs()
        self.go(GOTO)
        tabs = [{'tab_id': 'x', 'url': self.f.navigated_tab['url'], 'title': self.f.navigated_tab['title']}]
        self.assertIsNotNone(remembered_tab(self.f, AGENT_PID, tabs))
        self.assertIsNone(remembered_tab(self.f, 1, tabs))


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
