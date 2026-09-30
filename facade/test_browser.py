"""CE-FACADE-007 slice 1: navigation as a cua_do step, verified by where the tab landed.

Real captured Chrome tree (live_booking_ax.json) for the page after landing; the Driver's browser tools are faked with the shapes documented
in the Driver's browser-semantic-snapshots reference (page.url, page.title). No desktop, browser or network. Each test names the tempting
wrong patch it fails.
"""
import copy
import unittest

import browser
import test_live_shapes as lv
from core import OBSERVE_RETRY_DELAYS

BOOKING = 'https://clinic.example/booking'


class BrowserDriver(lv.LiveDriver):
    """LiveDriver plus the Driver's browser tools. `landed` is what the tab reports after browser_navigate; `refuse` maps tool -> refusal code."""
    def __init__(self):
        super().__init__('live_booking_ax.json')
        self.browser_calls = [];self.refuse = {};self.landed = {'url': BOOKING, 'title': 'Booking'};self.pages = None
        self.tabs = [{'tab_id': 'tab-1', 'active': True}];self.hotkeys = [];self.cmd_t_works = self.cmd_w_works = True;self.pending_tab = None;self.cmd_t_lag = 0;self.appear_after = 0
    def call(self, tool, args, timeout=20):
        if tool.startswith('browser_') or tool == 'get_browser_state':
            self.browser_calls.append((tool, copy.deepcopy(args)))
            mode = 'snapshot' if 'target_id' in args and tool == 'get_browser_state' else tool
            code = self.refuse.get(mode)
            if code:
                self.refuse.pop(mode) if mode == 'get_browser_state' and self.refuse.get('once') else None
                return {'status': 'refused', 'refusal': {'code': code}}
            if tool == 'get_browser_state' and 'target_id' not in args and self.pending_tab:
                if self.appear_after <= 0:
                    for t in self.tabs:t['active'] = False
                    self.tabs.append({'tab_id': self.pending_tab, 'active': True});self.pending_tab = None
                else:
                    self.appear_after -= 1
            if tool == 'get_browser_state' and 'target_id' not in args:
                return {'status': 'ok', 'mode': 'bind', 'target_id': 'bt-1', 'tabs': copy.deepcopy(self.tabs)}
            if tool == 'get_browser_state':
                page = self.pages.pop(0) if self.pages else self.landed
                return {'status': 'ok', 'mode': 'snapshot', 'page': dict(page)}
            return {'status': 'ok'}
        if tool == 'hotkey':
            self.hotkeys.append(list(args['keys']))
            if args['keys'] == ['cmd', 't'] and self.cmd_t_works:
                self.pending_tab = 'tab-new-%d' % len(self.hotkeys)
                self.appear_after = self.cmd_t_lag
            if args['keys'] == ['cmd', 'w'] and self.cmd_w_works:
                self.tabs = [t for t in self.tabs if not t.get('active')]
                if self.tabs:self.tabs[0]['active'] = True
            return {'effect': 'unverifiable'}
        return super().call(tool, args, timeout)
    def called(self, tool):
        return [a for t, a in self.browser_calls if t == tool]


class Base(lv.LiveBase):
    def setUp(self):
        super().setUp();self.driver = BrowserDriver()
        self.f = lv.Facade(self.driver, generic_factory=lambda: self.chooser, reader_factory=lambda: self.reader, visual_factory=lambda: self.visual, sleep=self.naps.append)
    def plan(self, steps, **kw):
        return self.f.do('Open the booking page', title='Demo', expect=None, steps=steps, **kw)


class Landing(unittest.TestCase):
    """The pure verdict. Wrong patch: 'navigate returned ok' means landed; or string-equality on the URL (https upgrade and ?ref= fail)."""
    def test_same_page_variants_are_ok(self):
        for got in (BOOKING, BOOKING + '/', 'https://www.clinic.example/booking', 'http://clinic.example/booking?ref=x#top'):
            self.assertEqual(browser.landing(BOOKING, got), 'ok', got)

    def test_another_page_or_host_is_elsewhere(self):
        self.assertEqual(browser.landing(BOOKING, 'https://clinic.example/booking/other'), 'navigated_elsewhere')
        self.assertEqual(browser.landing(BOOKING, 'https://clinic.example.evil.test/booking'), 'navigated_elsewhere')

    def test_a_sign_in_page_is_a_login_wall(self):
        self.assertEqual(browser.landing(BOOKING, 'https://clinic.example/login?next=/booking'), 'login_wall')
        self.assertEqual(browser.landing(BOOKING, 'https://idp.example/oauth2/authorize'), 'login_wall')
        self.assertEqual(browser.landing(BOOKING, 'https://clinic.example/portal', 'Sign in to Clinic'), 'login_wall')

    def test_asking_for_the_login_page_is_not_a_wall(self):
        self.assertEqual(browser.landing('https://clinic.example/login', 'https://clinic.example/login'), 'ok')

    def test_no_url_is_unknown(self):
        self.assertEqual(browser.landing(BOOKING, ''), 'unknown')


class Goto(Base):
    def test_goto_lands_and_verifies_expect(self):
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.called('browser_navigate')[0]['url'], BOOKING)
        self.assertEqual(r['steps'][0]['page']['url'], BOOKING)

    def test_a_redirect_stops_the_plan_before_the_next_step(self):
        # Wrong patch: treat the navigate call's success as landing, then press on whatever page loaded.
        self.driver.landed = {'url': 'https://ads.example/promo', 'title': 'Promo'}
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}, {'do': 'press', 'control': 'Book', 'expect': 'Booked:'}])
        self.assertNotEqual(r['status'], 'done')
        self.assertEqual(r['steps'][0]['reason'], 'navigated_elsewhere')
        self.assertEqual(len(r['steps']), 1, 'the press step must not run')
        self.assertEqual(self.driver.executed, [], 'nothing clicked')

    def test_a_login_wall_is_reported_and_nothing_typed(self):
        self.driver.landed = {'url': 'https://clinic.example/signin', 'title': 'Sign in'}
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'login_wall')
        self.assertEqual(self.driver.executed, [])

    def test_a_loading_tab_is_waited_out_within_the_look_delays(self):
        # Wrong patch: fail on the first empty URL (a page that has not committed yet), or poll without a bound.
        self.driver.pages = [{'url': '', 'title': ''}, {'url': 'about:blank', 'title': ''}]
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.naps[:2], list(OBSERVE_RETRY_DELAYS))

    def test_a_tab_that_never_reports_a_url_is_landing_unknown(self):
        self.driver.landed = {'url': '', 'title': ''}
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'landing_unknown')
        self.assertLessEqual(sum(self.naps), sum(OBSERVE_RETRY_DELAYS) + 0.001, 'bounded wait')

    def test_bad_urls_are_refused_before_any_driver_call(self):
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'clinic.example/booking', ''):
            r = self.plan([{'do': 'goto', 'url': url, 'expect': 'x'}])
            self.assertEqual(r['status'], 'refused', url)
        self.assertEqual(self.driver.browser_calls, [])

    def test_goto_takes_only_url_goal_and_expect(self):
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'control': 'Book', 'expect': 'x'}])
        self.assertEqual(r['status'], 'refused')


class Permission(Base):
    """Wrong patch: when the user's profile is refused, prepare an isolated profile (allow_launch) and carry on in another browser."""
    def test_a_refused_attach_is_permission_required_and_never_another_browser(self):
        self.driver.refuse = {'get_browser_state': 'browser_requires_setup', 'browser_prepare': 'existing_profile_not_granted'}
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'permission_required')
        self.assertIn('--grant existing-profile', r['steps'][0].get('message', ''))
        self.assertEqual(self.driver.called('browser_navigate'), [], 'nothing navigated')
        for args in self.driver.called('browser_prepare'):
            self.assertNotIn('allow_launch', args);self.assertNotIn('profile', args)
            self.assertEqual(args.get('strategy'), {'kind': 'existing_profile'})

    def test_setup_then_bind_uses_the_existing_profile(self):
        self.driver.refuse = {'get_browser_state': 'browser_requires_setup', 'once': True}
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.called('browser_prepare')[0]['strategy'], {'kind': 'existing_profile'})

    def test_several_tabs_with_none_active_is_ambiguous_not_a_guess(self):
        self.driver.tabs = [{'tab_id': 'a'}, {'tab_id': 'b'}]
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'browser_tab_ambiguous')
        self.assertEqual(self.driver.called('browser_navigate'), [])



class Tabs(Base):
    def test_open_tab_opens_one_new_active_tab_and_lands(self):
        r = self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.hotkeys, [['cmd', 't']])
        self.assertEqual(self.driver.called('browser_navigate')[-1]['tab_id'], 'tab-new-1', 'navigates the NEW tab, not the user tab')
        self.assertEqual([t['tab_id'] for t in self.driver.tabs], ['tab-1', 'tab-new-1'])

    def test_a_cmd_t_that_opens_nothing_is_not_retried_and_navigates_nothing(self):
        # Wrong patch: press Cmd+T again (a slow tab would make two), or navigate the user's current tab instead.
        self.driver.cmd_t_works = False
        r = self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened')
        self.assertEqual(self.driver.hotkeys, [['cmd', 't']])
        self.assertEqual(self.driver.called('browser_navigate'), [])

    def test_a_slow_new_tab_is_waited_for(self):
        # Wrong patch: stop waiting at the first poll (a Cmd+T that worked a moment later reads as tab_not_opened).
        self.driver.cmd_t_lag = 1
        r = self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.hotkeys, [['cmd', 't']])

    def test_close_tab_never_closes_a_tab_the_user_had(self):
        # Wrong patch: Cmd+W on whatever tab is active (closes the user's own logged-in tab).
        r = self.plan([{'do': 'close_tab'}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertEqual(self.driver.hotkeys, [], 'nothing pressed')
        self.assertEqual([t['tab_id'] for t in self.driver.tabs], ['tab-1'])

    def test_open_then_close_in_a_later_call_closes_only_that_tab(self):
        self.assertEqual(self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])['status'], 'done')
        r = self.plan([{'do': 'close_tab'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual([t['tab_id'] for t in self.driver.tabs], ['tab-1'])
        again = self.plan([{'do': 'close_tab'}])
        self.assertEqual(again['steps'][0]['reason'], 'tab_not_opened_by_facade', 'the user tab is next: refused')

    def test_a_cmd_w_that_closes_nothing_is_not_retried(self):
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.driver.cmd_w_works = False
        r = self.plan([{'do': 'close_tab'}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_closed')
        self.assertEqual(self.driver.hotkeys.count(['cmd', 'w']), 1)

    def test_switching_to_a_user_tab_before_close_is_refused(self):
        # Wrong patch: remember "we opened a tab" instead of checking that the ACTIVE tab is ours.
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        for t in self.driver.tabs:t['active'] = t['tab_id'] == 'tab-1'
        r = self.plan([{'do': 'close_tab'}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)


if __name__ == '__main__':
    unittest.main()
