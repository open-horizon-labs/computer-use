"""The resize plan step (#78, CE-FACADE-009): resizes ONLY the agent browser window, kept inside the agent display, done only on the Driver's confirmed
readback and an independent re-check. Fakes only: no launch, no desktop. Each test names the wrong patch it fails."""
import unittest

import test_agent_browser as ta
import test_browser as tb
from agent_browser import RESIZE_TOLERANCE
from plan import HINTS

DISPLAY = ta.DISPLAY
RESIZE = {'do': 'resize', 'width': 520, 'height': 1000}


class ResizeDriver(ta.AgentDriver):
    """set_window_frame as the Driver answers it (confirmed effect + readback); `mode` bends it."""
    def __init__(self, world, spaces):
        super().__init__(world);self.mode, self.spaces, self.frames = 'ok', spaces, []
    def call(self, tool, args, timeout=20):
        if tool != 'set_window_frame':
            return super().call(tool, args, timeout)
        frame = {k: args[k] for k in ('x', 'y', 'width', 'height')}
        self.frames.append((args['pid'], args['window_id'], frame))
        if self.mode == 'refuse':
            return {'status': 'refused', 'refusal': {'code': 'window_id belongs to pid in WindowServer but has no matching AXWindow'}}
        if self.mode == 'unconfirmed':
            return {'effect': 'unverifiable', 'readback': frame}
        if self.mode == 'no_readback':
            return {'effect': 'confirmed'}
        if self.mode == 'bad_readback':
            return {'effect': 'confirmed', 'readback': {**frame, 'width': frame['width'] + 40}}
        if self.mode == 'off_by_one':
            self.world.bounds = {**frame, 'width': frame['width'] + 1.5}
            return {'effect': 'confirmed', 'readback': self.world.bounds}
        if self.mode == 'listing_differs':  # the Driver says so, the window list does not agree
            return {'delivery': {'mode': 'not_applicable'}, 'effect': 'confirmed', 'evidence': [{'kind': 'value_readback', 'detail': 'WindowServer matched the requested frame within 2 points'}]}  # the real Driver 0.31 shape (live 2026-10-01)
        self.world.bounds = frame
        if self.mode == 'display_moved':  # the display layout changed under the window: it now sticks out
            self.spaces.displays = lambda: [{'id': 6, 'x': -1920, 'y': 0, 'width': 400, 'height': 1080}]
        return {'delivery': {'mode': 'not_applicable'}, 'effect': 'confirmed', 'evidence': [{'kind': 'value_readback', 'detail': 'WindowServer matched the requested frame within 2 points'}]}  # the real Driver 0.31 shape (live 2026-10-01)


class ResizeBase(ta.Base):
    def setup(self, **kw):
        self.make(**kw)
        self.driver = ResizeDriver(self.world, self.spaces)
        self.f.driver = self.driver
        self.f.do('Open the page', title='Demo', expect=None, steps=[ta.GOTO])
        self.driver.frames.clear()
        return self.f
    def resize(self, step=RESIZE, **kw):
        return self.f.do('Make the window narrow', **{'title': 'Demo', 'expect': None, 'steps': [step], **kw})
    def last(self):
        return self.driver.frames[-1][2]


class Resize(ResizeBase):
    def test_a_resize_keeps_x_y_and_is_done_on_confirmed_readback(self):
        # Wrong patch: send a frame without the current x, y (the Driver requires all four), or call it done without the readback.
        self.setup()
        r = self.resize()
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.frames, [(ta.AGENT_PID, ta.AGENT_WIN, {'x': -1880.0, 'y': 40.0, 'width': 520, 'height': 1000})])
        self.assertEqual(r['steps'][0]['resize'], {'x': -1880.0, 'y': 40.0, 'width': 520, 'height': 1000, 'clamped': False})
        self.assertEqual(r['summary']['window'], {'pid': ta.AGENT_PID, 'window_id': ta.AGENT_WIN})

    def test_a_resize_larger_than_the_display_is_clamped_and_the_window_stays_inside(self):
        # Wrong patch: send the requested size unclamped (the window then covers the user's screen).
        self.setup()
        r = self.resize({'do': 'resize', 'width': 3000, 'height': 2000})
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.last(), {'x': -1880.0, 'y': 40.0, 'width': 1840.0, 'height': 1000.0})  # display inset by RESIZE_MARGIN: live, Chrome settles an oversize window there and the Driver answers unverifiable for a full-display request
        self.assertTrue(r['steps'][0]['resize']['clamped'])
        self.assertTrue(self.agent.inside(self.world.bounds))

    def test_a_window_near_the_edge_is_moved_in_not_left_sticking_out(self):
        # Wrong patch: clamp the size but keep x, y (a wide window at the right edge would leave the display).
        self.setup()
        self.world.bounds = {'x': -400.0, 'y': 900.0, 'width': 300.0, 'height': 150.0}
        r = self.resize({'do': 'resize', 'width': 800, 'height': 600})
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.last(), {'x': -840.0, 'y': 440.0, 'width': 800, 'height': 600})

    def test_a_readback_within_two_points_is_accepted(self):
        self.setup()
        self.driver.mode = 'off_by_one'
        self.assertEqual(self.resize()['status'], 'done')
        self.assertEqual(RESIZE_TOLERANCE, 2.0)

    def test_the_next_look_does_not_bind_to_a_look_taken_before_the_resize(self):
        # Wrong patch: keep the cached look (its look_id would still bind to the old, wider page).
        self.setup()
        self.f.looks[(ta.AGENT_PID, ta.AGENT_WIN, 'old-look')] = {'created': 0}
        self.f.looks[(1, 2, 'user-look')] = {'created': 0}
        self.f.latest[(ta.AGENT_PID, ta.AGENT_WIN)] = 'handle'
        self.assertEqual(self.resize()['status'], 'done')
        self.assertEqual([k[2] for k in self.f.looks], ['user-look'])
        self.assertNotIn((ta.AGENT_PID, ta.AGENT_WIN), self.f.latest)
        stale = self.f.do('Press', pid=ta.AGENT_PID, window_id=ta.AGENT_WIN, expect=None, look_id='old-look', steps=[{'do': 'verify', 'expect': 'x'}])
        self.assertEqual(stale.get('reason'), 'unknown_look_id')

    def test_a_resize_can_start_a_plan_with_no_title_and_end_with_a_goto(self):
        self.setup()
        r = self.f.do('Narrow then open', expect=None, steps=[RESIZE, ta.GOTO])
        self.assertEqual([s['do'] for s in r['steps']], ['resize', 'goto'], r)
        self.assertEqual(r['steps'][0]['status'], 'done')


class Refusals(ResizeBase):
    def refused(self, r, reason):
        self.assertEqual((r['status'], r.get('reason')), ('refused', reason), r)
        self.assertEqual(self.driver.frames, [], 'no frame may be sent')
        self.assertEqual(r.get('hint'), HINTS[reason] % {'n': 1})
        self.assertLessEqual(len(r.get('hint', '')), 240)

    def test_the_users_window_is_never_resized(self):
        # Wrong patch: resize whatever pid and window_id the caller names (the user's own Chrome window).
        self.setup()
        r = self.f.do('Narrow', pid=1, window_id=2, expect=None, steps=[RESIZE])
        self.refused(r, 'resize_not_agent_window')

    def test_a_window_titled_by_the_caller_in_user_mode_is_not_resized(self):
        self.make(mode='user')
        self.driver = ResizeDriver(self.world, self.spaces);self.f.driver = self.driver
        self.refused(self.resize(), 'resize_not_agent_window')

    def test_profile_user_is_refused_before_anything_runs(self):
        self.setup()
        self.refused(self.resize({**RESIZE, 'profile': 'user'}), 'resize_not_agent_window')

    def test_another_window_id_in_the_agent_process_is_not_resized(self):
        self.setup()
        self.refused(self.f.do('Narrow', pid=ta.AGENT_PID, window_id=ta.AGENT_WIN + 1, expect=None, steps=[RESIZE]), 'resize_not_agent_window')

    def test_no_agent_browser_window_is_refused_and_nothing_is_launched(self):
        self.make()
        self.driver = ResizeDriver(self.world, self.spaces);self.f.driver = self.driver
        r = self.resize()
        self.refused(r, 'resize_no_agent_window')
        self.assertEqual(self.world.commands, [])

    def test_the_driver_refusal_is_typed_and_carries_no_driver_text(self):
        self.setup()
        self.driver.mode = 'refuse'
        r = self.resize()
        self.assertEqual((r['status'], r.get('reason'), r['delivery']), ('refused', 'resize_refused', 'none'), r)
        self.assertNotIn('WindowServer', r['steps'][0]['message'] + r['hint'])

    def test_bad_sizes_are_refused_in_validation(self):
        self.setup()
        for bad in ({'width': 'wide', 'height': 500}, {'width': 520}, {'width': 10, 'height': 500}, {'width': True, 'height': 500}, {'width': 520.5, 'height': 500}):
            r = self.resize({'do': 'resize', **bad})
            self.assertEqual(r.get('reason'), 'bad_request', bad)
        self.assertEqual(self.driver.frames, [])

    def test_every_resize_reason_has_a_hint_of_at_most_240_characters_naming_the_next_call(self):
        for reason in ('resize_not_agent_window', 'resize_no_agent_window', 'resize_refused', 'resize_unverified', 'resize_outside_display'):
            self.assertIn(reason, HINTS)
            self.assertLessEqual(len(HINTS[reason]), 240, reason)


class NotProven(ResizeBase):
    def test_an_effect_that_is_not_confirmed_is_not_done(self):
        # Wrong patch: treat a delivered set_window_frame as done without the Driver's confirmation.
        self.setup()
        self.driver.mode = 'unconfirmed'
        r = self.resize()
        self.assertEqual((r['status'], r.get('reason'), r['delivery']), ('failed', 'resize_unverified', 'uncertain'), r)

    def test_a_confirmed_effect_without_a_readback_is_not_done(self):
        # Wrong patch: accept effect=confirmed alone, no readback.
        self.setup()
        self.driver.mode = 'no_readback'
        self.assertEqual(self.resize().get('reason'), 'resize_unverified')

    def test_a_readback_off_by_more_than_two_points_is_not_done(self):
        # Wrong patch: a loose tolerance, or no comparison with the requested frame.
        self.setup()
        self.driver.mode = 'bad_readback'
        self.assertEqual(self.resize().get('reason'), 'resize_unverified')

    def test_a_window_list_that_disagrees_with_the_readback_is_not_done(self):
        # Wrong patch: trust the Driver's answer without listing the window again.
        self.setup()
        self.driver.mode = 'listing_differs'
        r = self.resize()
        self.assertEqual(r.get('reason'), 'resize_outside_display', r)
        self.assertEqual(len(self.driver.frames), 2, 'the old frame is put back once, best effort')
        self.assertEqual(self.driver.frames[-1][2], {'x': -1880.0, 'y': 40.0, 'width': 1840.0, 'height': 1000.0})

    def test_a_window_that_ends_outside_the_display_is_refused_even_with_a_matching_readback(self):
        # Wrong patch: skip the whole-window-inside re-check (the display layout can move under the window).
        self.setup()
        self.driver.mode = 'display_moved'
        r = self.resize()
        self.assertEqual((r['status'], r.get('reason')), ('failed', 'resize_outside_display'), r)
        self.assertLessEqual(len(r.get('hint', '')), 240)


if __name__ == '__main__':
    unittest.main()
