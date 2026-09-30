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
from test_live_shapes import add

BOOKING = 'https://clinic.example/booking'


class BrowserDriver(lv.LiveDriver):
    """LiveDriver plus the Driver's browser tools, shaped like 0.31.0 measured live: EVERY bind re-mints target_id and tab ids (a remembered
    id means nothing on the next bind); tabs carry url, title and active; Cmd+T opens an active new-tab page; browser_navigate changes the
    url of the tab its id pointed to in the bind that minted it. `landed` overrides where a navigation ends up; `refuse` maps tool -> code."""
    def __init__(self):
        super().__init__('live_booking_ax.json')
        self.browser_calls = [];self.refuse = {};self.landed = None;self.pages = None
        self.tabs = [{'url': 'https://mail.example/inbox', 'title': 'Inbox', 'active': True}]
        self.memory = '32.4';self.strip = False;self.close_works = True;self.close_of = {};self.clicked_close = [];self.script = self._tab_strip
        self.hotkeys = [];self.cmd_t_works = self.cmd_w_works = True;self.cmd_t_lag = 0;self.pending = 0;self.minted = {};self.binds = 0;self.navigated = False;self.foreground_keys = []
    def call(self, tool, args, timeout=20):
        if tool.startswith('browser_') or tool == 'get_browser_state':
            self.browser_calls.append((tool, copy.deepcopy(args)))
            mode = 'snapshot' if 'target_id' in args and tool == 'get_browser_state' else tool
            code = self.refuse.get(mode)
            if code:
                if mode == 'get_browser_state' and self.refuse.get('once'):self.refuse.pop(mode)
                return {'status': 'refused', 'refusal': {'code': code}}
            if tool == 'get_browser_state' and 'target_id' not in args:
                if self.pending:
                    self.pending -= 1
                    if self.pending == 0:self._add_tab()
                self.binds += 1;self.minted = {}
                out = []
                for i, t in enumerate(self.tabs):
                    tid = 'tab-%d-%d' % (self.binds, i);self.minted[tid] = i
                    out.append({**t, 'active': t['active'] and not self.navigated, 'tab_id': tid})
                active = [t for t in self.tabs if t['active']]
                return {'status': 'ok', 'mode': 'bind', 'target_id': 'bt-%d' % self.binds, 'tabs': out[::-1],
                        'native_title': (active[0]['title'] + ' - Google Chrome') if active else ''}
            if tool == 'browser_navigate':
                i = self.minted[args['tab_id']]
                dest = self.landed or {'url': args['url'], 'title': 'Booking'}
                self.tabs[i].update(dest);self.navigated = True
                return {'status': 'ok'}
            if tool == 'get_browser_state':
                if self.pages:return {'status': 'ok', 'mode': 'snapshot', 'page': dict(self.pages.pop(0))}
                t = self.tabs[self.minted[args['tab_id']]]
                return {'status': 'ok', 'mode': 'snapshot', 'page': {'url': t['url'], 'title': t['title']}}
            return {'status': 'ok'}
        if tool == 'click' and self.close_of:
            tab = self.close_of.get(int(args['element_token'].rsplit(':', 1)[1]))
            if tab is not None:
                self.clicked_close.append(tab['url'])
                if self.close_works:
                    self.tabs = [t for t in self.tabs if t is not tab]
                    if self.tabs and not any(t['active'] for t in self.tabs):self.tabs[-1]['active'] = True
        if tool == 'hotkey':
            self.hotkeys.append(list(args['keys']))
            if args.get('delivery_mode') == 'foreground':self.foreground_keys.append(list(args['keys']))
            if args['keys'] == ['cmd', 'w'] and args.get('delivery_mode') != 'foreground':
                return {'effect': 'unverifiable'}  # measured live: Chrome ignores a background Cmd+W
            if args['keys'] == ['cmd', 't'] and self.cmd_t_works:
                if self.cmd_t_lag:self.pending = self.cmd_t_lag + 1
                else:self._add_tab()
            if args['keys'] == ['cmd', 'w'] and self.cmd_w_works:
                self.tabs = [t for t in self.tabs if not t['active']]
                if self.tabs:self.tabs[-1]['active'] = True
            return {'effect': 'unverifiable'}
        return super().call(tool, args, timeout)
    def _tab_strip(self, driver, els):
        """Chrome's tab strip as issue #4 measured it: an AXTabGroup of one AXRadioButton per tab (named with the tab title, in WINDOW order),
        each with an AX child button named Close. SYNTHETIC shape (no live capture in facade/fixtures has a tab strip): roles and nesting
        follow the #4 comment and the label is modelled on the 2026-09-29 live capture ('<title> - Memory usage - 32.4 MB'); a live capture is still to be taken with the user's consent."""
        self.close_of = {}
        if not self.strip:return None
        add(els, 0, 'AXTabGroup', label='', actions=['AXShowMenu']);group = els[-1]['element_index']
        for t in self.tabs:
            add(els, group, 'AXRadioButton', label=t['title'] + ' - Memory usage - %s MB' % self.memory, value='1' if t['active'] else '0');radio = els[-1]['element_index']
            add(els, radio, 'AXButton', label='Close');self.close_of[els[-1]['element_index']] = t
    def _add_tab(self):
        self.navigated = False
        for t in self.tabs:t['active'] = False
        self.tabs.append({'url': 'chrome://newtab/', 'title': 'New Tab', 'active': True})
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


class NavigateRefused(Base):
    def test_a_refusal_that_is_not_about_permission_is_not_reported_as_one(self):
        # Wrong patch: map every browser_navigate refusal to permission_required (live 2026-09-30: a goto to a 404 page said so).
        self.driver.refuse = {'browser_navigate': 'navigation_failed'}
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual((r['steps'][0]['status'], r['steps'][0]['reason']), ('refused', 'navigate_refused'))
        self.assertIn('navigation_failed', r['steps'][0].get('message', ''))

    def test_a_page_that_does_not_load_is_navigate_failed(self):
        # Wrong patch: a failed navigate call (no refusal code) reported as permission_required (live 2026-09-30, a 404).
        from core import DriverCallFailed
        real = self.driver.call
        def boom(tool, args, timeout=20):
            if tool == 'browser_navigate':raise DriverCallFailed('driver_call_failed: browser_navigate exited 1', tool, 'exit')
            return real(tool, args, timeout)
        self.driver.call = boom
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'navigate_failed')
        self.assertNotIn('permission', r['steps'][0].get('message', ''))

    def test_a_consent_refusal_is_still_permission_required(self):
        self.driver.refuse = {'browser_navigate': 'browser_consent_required'}
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'permission_required')


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
        self.driver.tabs = [{'url': 'https://a.example/', 'title': 'a', 'active': False}, {'url': 'https://b.example/', 'title': 'b', 'active': False}]
        r = self.plan([{'do': 'goto', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'browser_tab_ambiguous')
        self.assertEqual(self.driver.called('browser_navigate'), [])



class Tabs(Base):
    def test_open_tab_opens_one_new_active_tab_and_lands(self):
        r = self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.hotkeys, [['cmd', 't']])
        self.assertEqual(self.driver.tabs[0]['url'], 'https://mail.example/inbox', 'the user tab is never navigated')
        self.assertEqual(self.driver.tabs[1]['url'], BOOKING, 'the NEW tab was navigated')

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

    def test_tab_ids_are_never_remembered_across_binds(self):
        # Wrong patch (the one that failed live on 0.31.0): diff tab ids between binds; every id is new on every bind.
        r = self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['status'], 'done', r)
        self.assertGreater(self.driver.binds, 1, 'the check needs more than one bind for this test to mean anything')

    def test_a_user_tab_at_the_same_url_in_another_position_is_not_closed(self):
        # Wrong patch: recognise the tab by URL alone (two tabs at that URL: Cmd+W could close the user's).
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.driver.tabs[0].update(url=BOOKING)
        for t in self.driver.tabs:t['active'] = t is self.driver.tabs[0]
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)

    def test_a_tab_count_change_after_open_blocks_close(self):
        # Wrong patch: position + URL only; the user opened another tab, so positions may no longer mean the same tab.
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.driver.tabs.insert(0, {'url': 'https://x.example/', 'title': 'x', 'active': False})
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')

    def test_a_tab_added_after_ours_blocks_close_even_at_the_same_position(self):
        # Wrong patch: URL + title without the count (a tab added after ours: the window is not the one we left).
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.driver.tabs.append({'url': 'https://x.example/', 'title': 'x', 'active': False})
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)

    def test_another_tab_appearing_is_not_our_new_tab(self):
        # Wrong patch: 'one more tab' is enough. Cmd+T did nothing, a page opened a background tab: the active tab is still the user's.
        self.driver.cmd_t_works = False
        self.driver.tabs.append({'url': 'https://popup.example/', 'title': 'popup', 'active': False})
        original = self.driver.tabs
        self.driver.tabs = original[:1]
        def appear(tool, args, _call=self.driver.call):
            if tool == 'hotkey':self.driver.tabs = original
            return _call(tool, args)
        self.driver.call = appear
        r = self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened')
        self.assertEqual(self.driver.called('browser_navigate'), [], 'neither the user tab nor the popup is navigated')

    def test_our_tab_in_the_background_is_not_closed(self):
        # Wrong patch: URL unique + count, without asking which tab the WINDOW shows (Cmd+W closes that one, the user's).
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        for t in self.driver.tabs:t['active'] = t['url'] == 'https://mail.example/inbox'
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)

    def test_close_tab_without_a_tab_strip_control_presses_nothing_and_fronts_nothing(self):
        # Wrong patch: front the window and send Cmd+W without the step's allow_foreground (or send Cmd+W in the background: Chrome ignores it).
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        r = self.plan([{'do': 'close_tab'}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_close_control_not_found')
        self.assertEqual((self.driver.hotkeys, self.driver.foreground_keys, self.driver.executed), ([['cmd', 't']], [], []))
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.foreground_keys, [['cmd', 'w']], 'Cmd+W only, and only in the foreground')

    def test_a_user_tab_with_the_same_address_and_title_blocks_close(self):
        # Wrong patch: the URL need not be unique (the window shows one of two identical tabs: which one Cmd+W closes is unknown).
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.driver.tabs[0].update(url=BOOKING, title='Booking')
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)

    def test_close_tab_never_closes_a_tab_the_user_had(self):
        # Wrong patch: Cmd+W on whatever tab is active (closes the user's own logged-in tab).
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertEqual(self.driver.hotkeys, [], 'nothing pressed')
        self.assertEqual([t['url'] for t in self.driver.tabs], ['https://mail.example/inbox'])

    def test_open_then_close_in_a_later_call_closes_only_that_tab(self):
        self.assertEqual(self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])['status'], 'done')
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual([t['url'] for t in self.driver.tabs], ['https://mail.example/inbox'])
        again = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(again['steps'][0]['reason'], 'tab_not_opened_by_facade', 'the user tab is next: refused')

    def test_a_cmd_w_that_closes_nothing_is_not_retried(self):
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        self.driver.cmd_w_works = False
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_closed')
        self.assertEqual(self.driver.hotkeys.count(['cmd', 'w']), 1)

    def test_switching_to_a_user_tab_before_close_is_refused(self):
        # Wrong patch: remember "we opened a tab" instead of checking that the ACTIVE tab is ours.
        self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])
        for t in self.driver.tabs:t['active'] = t['url'] == 'https://mail.example/inbox'
        r = self.plan([{'do': 'close_tab', 'allow_foreground': True}])
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)


class TabStrip(Base):
    """close_tab presses the tab's own Close button (AX, background). Synthetic tab strip: see BrowserDriver._tab_strip."""
    def setUp(self):
        super().setUp();self.driver.strip = True
        self.assertEqual(self.plan([{'do': 'open_tab', 'url': BOOKING, 'expect': 'Dr. Priya Shah'}])['status'], 'done')
        self.driver.tabs[1]['title'] = 'Booking'
        self.f.opened_tabs[0]['title'] = 'Booking'
    def close(self, **step):
        return self.plan([{'do': 'close_tab', **step}])

    def test_close_presses_only_that_tabs_close_in_the_background_with_no_foreground(self):
        # Wrong patches: Cmd+W in the background (Chrome ignores it: the tab stays); front the window without allow_foreground.
        r = self.close()
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.clicked_close, [BOOKING])
        self.assertEqual([t['url'] for t in self.driver.tabs], ['https://mail.example/inbox'])
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)
        self.assertEqual(self.driver.foreground_keys, [])
        self.assertTrue(all(a.get('delivery_mode') != 'foreground' for a in self.driver.executed))

    def test_the_press_is_a_bound_observed_element_never_a_coordinate(self):
        self.close()
        self.assertEqual(len(self.driver.executed), 1)
        self.assertEqual(set(self.driver.executed[0]) - {'pid', 'window_id', 'session'}, {'element_token'})

    def test_a_tab_matched_by_url_only_is_not_enough(self):
        # Wrong patch: press the Close of whichever tab has the recorded URL, ignoring the tab strip's titles: the strip names no such tab.
        self.driver.tabs[1]['title'] = 'Renamed by the page'
        r = self.close()
        self.assertEqual(r['steps'][0]['reason'], 'tab_close_control_not_found')
        self.assertEqual((self.driver.clicked_close, len(self.driver.tabs)), ([], 2))

    def test_several_tabs_with_the_same_title_press_nothing(self):
        # Wrong patch: press the FIRST matching tab's Close (here the user's tab, listed first in the window).
        self.driver.tabs[0]['title'] = 'Booking'
        r = self.close()
        self.assertEqual(r['steps'][0]['reason'], 'tab_close_control_ambiguous')
        self.assertEqual((self.driver.clicked_close, self.driver.executed, len(self.driver.tabs)), ([], [], 2))

    def test_ambiguity_is_refused_even_with_allow_foreground(self):
        self.driver.tabs[0]['title'] = 'Booking'
        r = self.close(allow_foreground=True)
        self.assertEqual(r['steps'][0]['reason'], 'tab_close_control_ambiguous')
        self.assertNotIn(['cmd', 'w'], self.driver.hotkeys)

    def test_a_tab_without_a_close_child_is_refused_before_pressing(self):
        inner = self.driver._tab_strip
        def no_close(driver, els):
            inner(driver, els)
            for e in [e for e in els if e.get('label') == 'Close']:els.remove(e)
        self.driver.script = no_close
        r = self.close()
        self.assertEqual(r['steps'][0]['reason'], 'tab_close_control_not_found')
        self.assertEqual(self.driver.executed, [])

    def test_a_close_that_did_not_remove_the_tab_is_not_retried(self):
        # Wrong patch: press Close again (or fall back to Cmd+W) when the tab is still listed.
        self.driver.close_works = False
        r = self.close(allow_foreground=True)
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_closed')
        self.assertEqual((len(self.driver.executed), self.driver.hotkeys.count(['cmd', 'w'])), (1, 0))

    def test_the_url_and_count_identity_still_gates_the_press(self):
        # Wrong patch: trust the strip title alone: a changed tab count means it is not recognisably ours.
        self.driver.tabs.append({'url': 'https://x.example/', 'title': 'x', 'active': False})
        r = self.close()
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertEqual(self.driver.executed, [])

    def test_the_user_tab_is_never_pressed_after_ours_is_closed(self):
        self.assertEqual(self.close()['status'], 'done')
        r = self.close()
        self.assertEqual(r['steps'][0]['reason'], 'tab_not_opened_by_facade')
        self.assertEqual(len(self.driver.executed), 1)

    def test_a_fallback_is_used_only_when_the_strip_has_no_such_control_and_foreground_is_allowed(self):
        self.driver.strip = False
        r = self.close(allow_foreground=True)
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual((self.driver.foreground_keys, self.driver.executed), ([['cmd', 'w']], []))

    def test_a_title_that_only_extends_ours_is_not_our_tab(self):
        # Wrong patch: plain substring/prefix match ('Booking' matching 'Booking 2 - Memory usage - ...'): that tab would be pressed or make ours ambiguous.
        self.driver.tabs[0]['title'] = 'Booking 2'
        r = self.close()
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.clicked_close, [BOOKING])

    def test_a_tab_without_chromes_suffix_form_is_not_matched_by_a_loose_rule(self):
        self.assertTrue(browser._tab_label('Booking - Memory usage - 32.4 MB', 'Booking'))
        self.assertTrue(browser._tab_label('Booking', 'Booking'))
        self.assertFalse(browser._tab_label('Booking 2 - Memory usage - 1 MB', 'Booking'))
        self.assertFalse(browser._tab_label('My Booking - Memory usage - 1 MB', 'Booking'))

    def test_the_real_label_shape_is_found_not_only_the_bare_title(self):
        # Wrong patch: exact equality of label and title (never finds the tab live).
        self.assertIn('Memory usage', [e for e in self.driver.observe(1, 2)['elements'] if e['role'] == 'AXRadioButton'][0]['label'])
        self.assertEqual(self.close()['status'], 'done')

    def test_a_memory_number_change_between_bind_and_press_does_not_refuse(self):
        # Wrong patch: digest the readout number into the scope (the press then refuses on a value that changes every few seconds).
        real = self.driver.observe
        seen = []
        def drift(*a):
            seen.append(1);self.driver.memory = '%d.4' % (30 + len(seen));return real(*a)
        self.driver.observe = drift
        r = self.close()
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(len(seen), 2, 'one observe to find the control, one inside act to revalidate')

    def test_a_page_still_settling_during_the_close_is_retried_once(self):
        # Wrong patch: give up on the first StaleUI (live 2026-09-30: read_pages left its third tab open, tab_strip_changed, nothing pressed).
        real = self.driver.observe
        calls = []
        def settle(*a):
            calls.append(1)
            if len(calls) == 2:self.driver.memory = '77.7'  # something else in the window changes once, then holds
            out = real(*a)
            if len(calls) == 2:
                for e in out.get('elements', []):
                    if e.get('role') == 'AXStaticText':e['label'] = e['value'] = (e.get('label') or '') + ' '
            return out
        self.driver.observe = settle
        r = self.close()
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(len(self.driver.clicked_close), 1)

    def test_a_tab_title_change_between_bind_and_press_refuses(self):
        # Wrong patch: mask the whole label instead of only the number (a retitled tab would be pressed).
        real = self.driver.observe
        calls = []
        def retitle(*a):
            calls.append(1)
            if len(calls) >= 2:self.driver.tabs[1]['title'] = 'Booking (changed)'
            return real(*a)
        self.driver.observe = retitle
        r = self.close()
        # After one re-find (the close retries once on a stale strip) the retitled tab no longer matches: refused either way, never pressed.
        self.assertIn(r['steps'][0]['reason'], ('tab_strip_changed', 'tab_close_control_not_found'))
        self.assertEqual(self.driver.clicked_close, [])



class ReadoutMask(unittest.TestCase):
    """The memory-readout mask applies to tab-strip tabs only. Wrong patch: mask the pattern in every node (a page whose own text reads
    'Memory usage - 5 MB' and changes would then no longer invalidate a selection, S4.8)."""
    def digest_of(self, role, label):
        f = lv.Facade(lv.LiveDriver('live_booking_ax.json'))
        nodes = {0: {'element_index': 0, 'role': 'AXWindow', 'parent_index': None}, 1: {'element_index': 1, 'role': role, 'label': label, 'parent_index': 0}}
        return f.scope_digest({'raw': {'window_title': 'W'}, 'nodes': nodes}, 0) if hasattr(f, 'scope_digest') else None

    def test_page_text_is_not_masked(self):
        a, b = self.digest_of('AXStaticText', 'Memory usage - 5 MB'), self.digest_of('AXStaticText', 'Memory usage - 6 MB')
        if a is None:self.skipTest('scope_digest signature differs')
        self.assertNotEqual(a, b)

    def test_a_tab_readout_is_masked(self):
        a, b = self.digest_of('AXRadioButton', 'Booking - Memory usage - 5 MB'), self.digest_of('AXRadioButton', 'Booking - Memory usage - 6 MB')
        if a is None:self.skipTest('scope_digest signature differs')
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
