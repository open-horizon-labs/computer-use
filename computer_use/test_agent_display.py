"""Agent display policy (#60, CE-FACADE-009): windows the facade creates, and windows of agent-owned apps, are parked off the user's screen.

A fake spaces client is injected: no Swift, no helper, no desktop. Each test names the wrong patch it fails.
"""
import unittest

from agent_display import AgentDisplay, DEFAULT_AGENT_APPS
from core import Facade, Gap, MUTATING_TOOLS
from test_core import FakeDriver, FakeChooser, FakeReader, FakeVision


class FakeSpaces:
    """Stands in for spaces_client.SpaceMover; `log` is shared with the driver so ORDER is observable."""
    def __init__(self, log, fail=None):
        self.log, self.fail, self.parked, self.ensured = log, fail, [], 0
    def ensure_agent_display(self):
        self.ensured += 1
        if self.fail:raise self.fail
        return 6
    def park(self, window_id):
        self.ensure_agent_display()
        self.log.append(('park', window_id));self.parked.append(window_id);return {'moved': True}
    def stop(self):self.log.append(('stop',))


class NotFound(Exception):
    def __init__(self, message, detail):
        super().__init__(message);self.detail = detail
    code = 'window_not_moved'


class Unavailable(Exception):
    code = 'space_mover_unavailable'


class LoggedDriver(FakeDriver):
    def __init__(self, log, windows):
        super().__init__();self.log, self.windows = log, windows;self.calls = []
    def observe(self, *args):
        self.log.append(('driver', 'get_window_state'));return super().observe(*args)
    def call(self, tool, args, timeout=20):
        self.log.append(('driver', tool));self.calls.append((tool, dict(args)))
        if tool == 'list_windows':return {'windows': [dict(w) for w in self.windows]}
        return super().call(tool, args, timeout)


USER = {'pid': 1, 'window_id': 2, 'title': 'Demo', 'app_name': 'Google Chrome', 'is_on_screen': True}
EMU = {'pid': 11, 'window_id': 7, 'title': 'Android Emulator - Pixel:5554', 'app_name': 'qemu-system-aarch64', 'is_on_screen': True}
SIM = {'pid': 12, 'window_id': 8, 'title': 'iPhone 17', 'app_name': 'Simulator', 'is_on_screen': True}


class Base(unittest.TestCase):
    def make(self, windows, mode='auto', fail=None, apps=None):
        self.log = [];self.spaces = FakeSpaces(self.log, fail);self.driver = LoggedDriver(self.log, windows);self.naps = []
        self.agent = AgentDisplay(mode=mode, apps=apps, client=self.spaces, sleep=self.naps.append)
        self.f = Facade(self.driver, generic_factory=FakeChooser, reader_factory=FakeReader, visual_factory=FakeVision, sleep=lambda s: None, agent_display=self.agent)
        return self.f


class Created(Base):
    def test_a_created_window_is_parked_before_its_first_act(self):
        # Wrong patch: park after the first look/act (the agent drives it on the user's screen first), or never park a created window.
        f = self.make([USER])
        f.window_created(2, 'Fresh')
        f.observe(1, 2)
        self.assertEqual(self.spaces.parked, [2])
        self.assertLess(self.log.index(('park', 2)), self.log.index(('driver', 'get_window_state')))

    def test_the_summary_says_parked_once_and_only_then(self):
        # Wrong patch: add agent_display to every response (bigger responses), or never report it.
        f = self.make([USER])
        f.window_created(99, 'Fresh')
        self.assertEqual(f.look(title='Demo')['agent_display'], {'id': 6, 'parked': True})
        self.assertNotIn('agent_display', f.look(title='Demo'))

    def test_a_window_is_parked_at_most_once(self):
        # Wrong patch: park on every call (a move per look).
        f = self.make([USER]);f.window_created(99, 'Fresh');f.window_created(99, 'Fresh')
        self.assertEqual(self.spaces.parked, [99])


class Retry(Base):
    def test_a_window_not_yet_in_the_ax_list_is_retried_until_it_appears(self):
        # Wrong patch: give up at the first window_not_found (Chrome's new window is missing from AX for a moment), or retry forever.
        f = self.make([USER]);misses = [3]
        real = self.spaces.park
        def flaky(wid):
            if misses[0]:
                misses[0] -= 1;raise NotFound('window_not_found', {'code': 'window_not_found'})
            return real(wid)
        self.spaces.park = flaky
        self.assertTrue(f.window_created(99, 'Fresh'))
        self.assertEqual((self.spaces.parked, len(self.naps)), ([99], 3))

    def test_it_gives_up_after_twelve_tries_with_a_note(self):
        f = self.make([USER])
        def never(wid):raise NotFound('window_not_found', {'code': 'window_not_found'})
        self.spaces.park = never
        self.assertFalse(f.window_created(99, 'Fresh'))
        self.assertEqual(len(self.naps), 11)
        self.assertIn('window_not_found', f.look(title='Demo')['agent_display_note'])

    def test_a_window_without_a_known_title_is_not_parked(self):
        # Wrong patch: park the instant an id exists (before the window is real and named), or park an id nobody created.
        f = self.make([USER])
        self.assertFalse(f.window_created(99))
        self.assertEqual(self.spaces.parked, [])

    def test_other_failures_are_not_retried(self):
        f = self.make([USER]);f.spaces = None
        def untrusted(wid):raise NotFound('no grant', {'code': 'window_not_moved'})
        self.spaces.park = untrusted
        f.window_created(99, 'Fresh')
        self.assertEqual(self.naps, [])


class UserWindows(Base):
    def test_a_user_window_of_a_shared_app_is_never_parked(self):
        # Wrong patch: park whatever the inventory lists, or every window of a browser the user shares.
        f = self.make([USER, {**USER, 'window_id': 3, 'title': 'Mail', 'app_name': 'Finder'}])
        r = f.look(title='Demo');f.windows()
        self.assertEqual(self.spaces.parked, [])
        self.assertEqual(self.spaces.ensured, 0, 'the display is not even started')
        self.assertNotIn('agent_display', r)

    def test_chrome_beta_is_agent_owned_but_chrome_is_not(self):
        # Wrong patch: a substring match on "Chrome" that moves the user's own browser.
        f = self.make([USER, {**USER, 'window_id': 4, 'title': 'B', 'app_name': 'Google Chrome Beta'}])
        f.windows()
        self.assertEqual(self.spaces.parked, [4])
        self.assertIn('Simulator', DEFAULT_AGENT_APPS);self.assertIn('Android Emulator', DEFAULT_AGENT_APPS)


class AgentOwned(Base):
    def test_agent_owned_app_windows_are_parked_and_shared_ones_are_not(self):
        f = self.make([USER, EMU, SIM])
        f.windows();r = f.look(title='Demo')  # only windows the facade observes are considered: the title filter hides the others
        self.assertEqual(sorted(self.spaces.parked), [7, 8])
        self.assertEqual(r['agent_display'], {'id': 6, 'parked': True})
        f.windows();self.assertEqual(sorted(self.spaces.parked), [7, 8], 'each is parked once')

    def test_an_off_screen_window_is_not_moved(self):
        # Wrong patch: move windows on another Space (not on the user's screen; the move could not be verified).
        f = self.make([{**EMU, 'is_on_screen': False}]);f.windows()
        self.assertEqual(self.spaces.parked, [])

    def test_the_app_list_is_configurable(self):
        f = self.make([USER, EMU], apps=['Google Chrome']);f.windows()
        self.assertEqual(self.spaces.parked, [2])


class Modes(Base):
    def test_off_parks_nothing_and_never_starts_the_display(self):
        # Wrong patch: read the setting only for created windows, so agent-owned apps are still moved with the feature off.
        f = self.make([USER, EMU], mode='off')
        f.window_created(99, 'Fresh');f.windows();r = f.look(title='Demo')
        self.assertEqual((self.spaces.parked, self.spaces.ensured), ([], 0))
        self.assertNotIn('agent_display', r);self.assertNotIn('agent_display_note', r)

    def test_auto_continues_with_a_one_line_note_when_unavailable(self):
        # Wrong patch: raise in auto (a missing helper breaks every look), or continue silently (the user's screen is used without telling).
        f = self.make([USER, EMU], fail=Unavailable('no helper'))
        f.windows();r = f.look(title='Demo')
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['agent_display_note'], 'agent_display: unavailable (space_mover_unavailable: no helper)')
        self.assertNotIn('\n', r['agent_display_note']);self.assertNotIn('agent_display', r)

    def test_unavailable_is_cached_not_retried_per_window(self):
        # Wrong patch: respawn the helper for every window or call.
        f = self.make([USER, EMU, SIM], fail=Unavailable('no helper'))
        f.windows();f.window_created(50, 'F');f.window_created(51, 'F')
        self.assertEqual(self.spaces.ensured, 1)

    def test_required_refuses_the_window_creating_step_with_a_typed_reason(self):
        # Wrong patch: required behaves like auto (continues on the user's screen), or refuses without a typed reason.
        f = self.make([USER], mode='required', fail=Unavailable('no helper'))
        with self.assertRaises(Gap) as caught:f.window_created(99, 'Fresh')
        self.assertTrue(str(caught.exception).startswith('agent_display_unavailable:'), caught.exception)
        self.assertEqual(self.spaces.parked, [])

    def test_required_refuses_a_look_that_would_show_an_agent_owned_window(self):
        f = self.make([USER, EMU], mode='required', fail=Unavailable('no helper'))
        with self.assertRaises(Gap) as caught:f.windows()
        self.assertTrue(str(caught.exception).startswith('agent_display_unavailable:'))
        self.assertEqual(f.do('x', title=EMU['title'], expect=None)['reason'], 'agent_display_unavailable')

    def test_required_with_a_working_helper_parks(self):
        f = self.make([EMU], mode='required');f.windows()
        self.assertEqual(self.spaces.parked, [7])


class NoForeground(Base):
    def test_parking_never_calls_a_foreground_route_or_a_mutating_tool(self):
        # Wrong patch: park by fronting or clicking/keying the window (set_window_frame, hotkey, foreground delivery) instead of the helper.
        f = self.make([USER, EMU, SIM]);f.window_created(99, 'Fresh');f.windows();f.look(title='Demo')
        tools = {t for t, _ in self.driver.calls}
        self.assertFalse(tools & MUTATING_TOOLS, tools)
        self.assertFalse([a for _, a in self.driver.calls if a.get('delivery_mode') == 'foreground'])

    def test_shutdown_stops_the_display_but_close_does_not(self):
        # Wrong patch: stop the display on finish/close (parked windows spill onto the user's screen mid-task), or never stop it.
        f = self.make([EMU]);f.windows()
        f.close();self.assertNotIn(('stop',), self.log)
        f.shutdown();self.assertIn(('stop',), self.log)


if __name__ == '__main__':
    unittest.main()
