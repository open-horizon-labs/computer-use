"""CE-FACADE-007 (#34): read_pages {urls, fields?}, a do step: for each url open_tab -> look -> close_tab, per-page landing verdict, look summary and look_id.

Same fakes as test_browser.py: the REAL captured Chrome booking tree behind a faked Driver browser (shapes measured live on 0.31.0) with a SYNTHETIC
tab strip. Each test names the tempting wrong patch it fails.
"""
import json
import unittest

import browser
import test_browser as tb
import test_live_shapes as lv

INBOX = 'https://mail.example/inbox'
A, B, C = 'https://clinic.example/booking', 'https://clinic.example/booking/b', 'https://clinic.example/booking/c'
ELSEWHERE = {'url': 'https://ads.example/promo', 'title': 'Promo'}
LOGIN = {'url': 'https://clinic.example/login?next=/booking/b', 'title': 'Sign in'}


class Clock:
    def __init__(self):self.now = 0.0
    def __call__(self):return self.now


class PagesDriver(tb.BrowserDriver):
    """`dest` maps a requested url to where its navigation really ends up; `tick` seconds pass on the injected clock at every Cmd+T."""
    def __init__(self, clock):
        super().__init__();self.dest = {};self.clock = clock;self.tick = 0;self.navigated_tabs = [];self.strip = True
    def call(self, tool, args, timeout=20):
        if tool == 'hotkey' and self.tick:self.clock.now += self.tick
        if tool == 'browser_navigate':
            self.navigated_tabs.append(args['tab_id'])
            self.landed = self.dest.get(args['url'])
        return super().call(tool, args, timeout)


class Base(lv.LiveBase):
    def setUp(self):
        super().setUp();self.clock = Clock();self.driver = PagesDriver(self.clock)
        self.f = lv.Facade(self.driver, generic_factory=lambda: self.chooser, reader_factory=lambda: self.reader, visual_factory=lambda: self.visual, sleep=self.naps.append, clock=self.clock)
    def read(self, urls, **kw):
        return self.f.do('Compare the booking pages', title='Demo', expect=None, steps=[{'do': 'read_pages', 'urls': urls, **kw}])
    def pages(self, result):
        return result['steps'][0]['pages']
    def assert_only_the_users_tab_remains(self):
        self.assertEqual([(t['url'], t['title']) for t in self.driver.tabs], [(INBOX, 'Inbox')])


class Reads(Base):
    def test_each_url_is_opened_looked_at_and_closed_in_one_call(self):
        r = self.read([A, B, C])
        self.assertEqual(r['status'], 'done', r)
        pages = self.pages(r)
        self.assertEqual([p['url'] for p in pages], [A, B, C])
        for p in pages:
            self.assertEqual((p['status'], p['landing'], p['closed']), ('ok', 'ok', True), p)
            self.assertTrue(p['look_id'].startswith('lk_'))
            self.assertEqual((p['summary']['record_kind'], p['summary']['records']), ('flat-list', 12))
            self.assertEqual(len(p['summary']['sample']), 3)
        self.assertEqual(self.driver.hotkeys, [['cmd', 't']] * 3, 'one new tab per page, closed through its own Close button')
        self.assertEqual(self.driver.foreground_keys, [], 'nothing was fronted')
        self.assert_only_the_users_tab_remains()
        self.assertEqual(len(self.driver.executed), len(self.driver.clicked_close), 'the only clicks are the Close buttons of the tabs this step opened')

    def test_the_users_tab_is_never_navigated(self):
        # Wrong patch: read each url by goto (navigate the window's active tab): the user's page is lost and never restored.
        self.read([A, B])
        self.assertEqual(len(self.driver.navigated_tabs), 2)
        self.assertTrue(all(t.endswith('-1') for t in self.driver.navigated_tabs), 'only the tab at index 1 (the new one) is navigated; index 0 is the user\'s: %s' % self.driver.navigated_tabs)
        self.assert_only_the_users_tab_remains()

    def test_a_page_that_lands_elsewhere_does_not_abort_the_others_silently(self):
        # Wrong patch: the first failing page ends the step (or is dropped from the result), so the caller compares two pages and never learns a third failed.
        self.driver.dest = {B: ELSEWHERE}
        r = self.read([A, B, C])
        pages = self.pages(r)
        self.assertEqual([p['url'] for p in pages], [A, B, C], 'one entry per url, in order')
        self.assertEqual([p['status'] for p in pages], ['ok', 'failed', 'ok'])
        self.assertEqual(pages[1]['landing'], 'navigated_elsewhere')
        self.assertIn('ads.example', pages[1]['message'])
        self.assertNotIn('look_id', pages[1], 'a page that did not land is not read')
        self.assertTrue(pages[2]['look_id'])
        self.assertEqual((r['status'], r['reason'], r['failed_step']), ('stopped', 'pages_incomplete', 1))
        self.assertIn('hint', r)
        self.assertTrue(all(p['closed'] for p in pages), 'the tab of the page that did not land is closed too: no stray tab')
        self.assert_only_the_users_tab_remains()

    def test_a_login_wall_is_reported_and_not_read(self):
        self.driver.dest = {B: LOGIN}
        pages = self.pages(self.read([A, B]))
        self.assertEqual((pages[1]['landing'], pages[1]['status']), ('login_wall', 'failed'))
        self.assertNotIn('look_id', pages[1]);self.assertEqual(len(self.driver.executed), len(self.driver.clicked_close), 'nothing was typed or pressed on the sign-in page')
        self.assert_only_the_users_tab_remains()

    def test_a_refused_attach_stops_every_page_with_its_reason_and_opens_nothing(self):
        self.driver.refuse = {'get_browser_state': 'browser_requires_setup', 'browser_prepare': 'existing_profile_not_granted'}
        r = self.read([A, B, C])
        pages = self.pages(r)
        self.assertEqual([(p['status'], p.get('reason')) for p in pages], [('failed', 'permission_required'), ('skipped', 'permission_required'), ('skipped', 'permission_required')])
        self.assertEqual((self.driver.hotkeys, self.driver.called('browser_navigate')), ([], []))
        self.assertEqual(r['status'], 'stopped')

    def test_a_tab_that_cannot_be_closed_stops_the_rest_instead_of_leaving_more_tabs(self):
        self.driver.strip = False  # the strip shows no Close button: close_tab refuses, nothing is pressed or fronted
        pages = self.pages(self.read([A, B, C]))
        self.assertEqual((pages[0]['status'], pages[0]['closed']), ('ok', False))
        self.assertEqual(pages[0]['close']['reason'], 'tab_close_control_not_found')
        self.assertEqual([(p['status'], p['reason']) for p in pages[1:]], [('skipped', 'previous_tab_not_closed')] * 2)
        self.assertEqual(self.driver.hotkeys, [['cmd', 't']], 'exactly one tab was opened')
        self.assertEqual(self.driver.foreground_keys, [])

    def test_the_total_budget_skips_the_rest_and_says_so(self):
        # Wrong patch: no total bound (5 slow pages run for minutes) or silently dropping the pages that did not fit.
        self.driver.tick = 40  # seconds per page on the injected clock; the plan grants 3 x budget_s = 60
        pages = self.pages(self.read([A, B, C]))
        self.assertEqual([p['status'] for p in pages], ['ok', 'ok', 'skipped'])
        self.assertEqual(pages[2]['reason'], 'budget_exceeded')
        self.assert_only_the_users_tab_remains()

    def test_a_tab_an_earlier_step_opened_is_not_closed_by_a_page_that_failed_to_open(self):
        # Wrong patch: close whatever open_tab last recorded for the window (here, the earlier step's tab).
        first = self.f.do('Open a tab', title='Demo', expect=None, steps=[{'do': 'open_tab', 'url': A, 'expect': None}])
        self.assertEqual(first['status'], 'delivered_unverified')
        self.driver.cmd_t_works = False
        pages = self.pages(self.read([B]))
        self.assertEqual(pages[0]['reason'], 'tab_not_opened')
        self.assertNotIn('closed', pages[0])
        self.assertEqual(self.driver.clicked_close, [])
        self.assertEqual(len(self.driver.tabs), 2, 'the earlier step\'s tab is still open')

    def test_the_earlier_steps_tab_is_still_closable_afterwards(self):
        self.f.do('Open a tab', title='Demo', expect=None, steps=[{'do': 'open_tab', 'url': A, 'expect': None}])
        self.driver.dest = {B: {'url': B, 'title': 'Booking B'}}  # a distinct title: the tab strip is matched by title
        self.assertEqual(self.read([B])['status'], 'done')
        closed = self.f.do('Close it', title='Demo', expect=None, steps=[{'do': 'close_tab'}])
        self.assertEqual(closed['status'], 'done', closed)
        self.assert_only_the_users_tab_remains()

    def test_fields_are_read_per_page_through_the_look(self):
        pages = self.pages(self.read([A], fields=lv.BOOKING_FIELDS))
        self.assertTrue(self.reader.requests, 'the extraction model ran on the page')
        self.assertIn('values', pages[0]['summary']['sample'][0])

    def test_the_response_stays_within_the_byte_budget_for_five_pages(self):
        r = self.read([A, B, C, A + '?x=1', B + '?x=2'])
        self.assertEqual(r['status'], 'done')
        self.assertLessEqual(len(json.dumps(r)), 6144)


class Redirect(Base):
    def test_open_tab_whose_landing_failed_leaves_a_tab_close_tab_can_close(self):
        # Wrong patch: only remember the tab when it landed, so a redirected tab stays open forever.
        self.driver.dest = {A: ELSEWHERE}
        first = self.f.do('Open', title='Demo', expect=None, steps=[{'do': 'open_tab', 'url': A, 'expect': None}])
        self.assertEqual(first['steps'][0]['reason'], 'navigated_elsewhere')
        self.assertEqual(len(self.driver.tabs), 2)
        closed = self.f.do('Close', title='Demo', expect=None, steps=[{'do': 'close_tab'}])
        self.assertEqual(closed['status'], 'done', closed)
        self.assert_only_the_users_tab_remains()


class Validation(Base):
    def refused(self, step, **kw):
        r = self.f.do('Compare', title='Demo', expect=None, steps=[step], **kw)
        self.assertEqual(r['status'], 'refused', r)
        self.assertEqual((self.driver.browser_calls, self.driver.hotkeys), ([], []), 'refused before any Driver action')
        return r

    def test_at_most_five_urls(self):
        r = self.refused({'do': 'read_pages', 'urls': [A, B, C, A + '?1', A + '?2', A + '?3']})
        self.assertIn('1 to 5', r['message'])

    def test_urls_are_required_and_checked(self):
        self.refused({'do': 'read_pages'})
        self.refused({'do': 'read_pages', 'urls': []})
        self.refused({'do': 'read_pages', 'urls': [A, 'file:///etc/passwd']})
        self.refused({'do': 'read_pages', 'urls': [A, 'javascript:alert(1)']})

    def test_it_takes_only_urls_fields_and_goal(self):
        self.refused({'do': 'read_pages', 'urls': [A], 'expect': 'x'})
        self.refused({'do': 'read_pages', 'urls': [A], 'allow_foreground': True})
        self.refused({'do': 'read_pages', 'urls': [A], 'fields': {}})

    def test_the_constants_are_the_documented_bounds(self):
        self.assertEqual(browser.READ_PAGES_MAX, 5)


if __name__ == '__main__':
    unittest.main()
