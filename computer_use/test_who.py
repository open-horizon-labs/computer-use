"""Window resolution, who-fixes-it on refusals, targeting by url, the per-window foreground grant and the unresolved-window re-read.
Each test names the tempting wrong patch it fails (scripts/check_plan_mutations.py applies the ones marked MUTATION). Fakes only."""
import unittest

from core import Facade, Gap, WindowRefusal
import mobile
import pageurl
import plan
from test_core import FakeDriver, FakeChooser, FakeReader, FakeVision


def win(pid, wid, title, app, **more):
    return {'pid': pid, 'window_id': wid, 'title': title, 'app_name': app, 'is_on_screen': True, 'layer': 0, **more}


class Windows(FakeDriver):
    """FakeDriver whose window list, browser tabs and observations the test sets."""
    def __init__(self, windows, tabs=None):
        super().__init__()
        self.windows, self.tabs, self.calls = windows, tabs or {}, []

    def call(self, tool, args, timeout=20):
        self.calls.append((tool, args.get('pid')))
        if tool == 'list_windows':
            return {'windows': [dict(w) for w in self.windows]}
        if tool == 'get_browser_state' and 'pid' in args:
            tabs = self.tabs.get((args['pid'], args['window_id']))
            if tabs is None:
                return {'refusal': {'code': 'browser_requires_setup'}}
            return {'target_id': 't%d' % args['window_id'], 'tabs': [dict(t) for t in tabs]}
        return super().call(tool, args, timeout)


def facade(driver):
    return Facade(driver, generic_factory=FakeChooser, reader_factory=FakeReader, visual_factory=FakeVision, sleep=lambda s: None)


def tab(i, url, active=False, title='t'):
    return {'tab_id': 'tab%d' % i, 'url': url, 'title': title, 'active': active}


class TitleResolution(unittest.TestCase):
    CHROME = win(1, 2, 'Principal AI Software Engineer', 'Google Chrome')
    NOTES = win(3, 4, 'Shopping list', 'Notes')

    def resolve(self, windows, title):
        return facade(Windows(windows)).resolve_window(title)

    def refusal(self, windows, title):
        with self.assertRaises(WindowRefusal) as caught:
            self.resolve(windows, title)
        return caught.exception

    def test_exact_title_wins_over_a_longer_title_that_contains_it(self):
        # Wrong patch: substring first (the exact window would be ambiguous with its longer neighbour).
        found = self.resolve([win(1, 2, 'Inbox', 'Mail'), win(1, 3, 'Inbox - archive', 'Mail')], 'Inbox')
        self.assertEqual(found['window_id'], 2)

    def test_a_unique_title_substring_binds_case_insensitively(self):
        self.assertEqual(self.resolve([self.CHROME, self.NOTES], 'ai software')['window_id'], 2)

    def test_an_app_name_with_one_window_binds_it(self):
        # The live failure: title="Chrome" for a window titled "Principal AI Software Engineer".
        for name in ('Chrome', 'Google Chrome', 'google chrome'):
            self.assertEqual(self.resolve([self.CHROME, self.NOTES], name)['window_id'], 2, name)

    def test_an_app_name_prefers_the_one_window_on_the_current_space(self):
        other_space = win(1, 9, 'Elsewhere', 'Google Chrome', is_on_screen=False)
        self.assertEqual(self.resolve([self.CHROME, other_space], 'Chrome')['window_id'], 2)

    def test_an_app_name_with_several_windows_is_ambiguous_with_candidates_and_binds_none(self):
        # MUTATION: bind the first of several windows of the app. Wrong patch: act on a guess between several.
        error = self.refusal([self.CHROME, win(1, 5, 'Workday', 'Google Chrome'), self.NOTES], 'Chrome')
        self.assertEqual(error.reason, 'window_ambiguous')
        self.assertEqual(sorted(c['title'] for c in error.candidates), ['Principal AI Software Engineer', 'Workday'])
        self.assertEqual({c['app'] for c in error.candidates}, {'Google Chrome'})

    def test_several_title_matches_are_ambiguous_not_the_first(self):
        error = self.refusal([win(1, 2, 'Report A', 'Pages'), win(1, 3, 'Report B', 'Pages'), self.NOTES], 'report')
        self.assertEqual((error.reason, len(error.candidates)), ('window_ambiguous', 2))

    def test_equal_titles_are_ambiguous_and_name_the_ids(self):
        error = self.refusal([win(1, 2, 'Demo', 'App'), win(1, 3, 'Demo', 'App')], 'Demo')
        self.assertEqual((error.reason, [(c['pid'], c['window_id']) for c in error.candidates]), ('window_ambiguous', [(1, 2), (1, 3)]))

    def test_nothing_matching_is_not_found_and_lists_the_open_windows_current_space_first(self):
        hidden = win(1, 9, 'Hidden', 'Mail', is_on_screen=False)
        error = self.refusal([hidden, self.CHROME, self.NOTES], 'Calculator')
        self.assertEqual(error.reason, 'window_not_found')
        self.assertEqual([c['title'] for c in error.candidates], ['Principal AI Software Engineer', 'Shopping list', 'Hidden'])

    def test_candidates_are_capped_at_eight(self):
        windows = [win(1, i, 'Doc %d' % i, 'Pages') for i in range(2, 14)]
        self.assertEqual(len(self.refusal(windows, 'Doc').candidates), 8)
        self.assertEqual(len(self.refusal(windows, 'Nothing').candidates), 8)

    def test_a_window_above_layer_zero_is_not_the_apps_window(self):
        # Wrong patch: count menu bars and overlays as windows (the app would look ambiguous, or an overlay would bind).
        overlay = win(1, 7, 'Overlay', 'Google Chrome', layer=25)
        self.assertEqual(self.resolve([self.CHROME, overlay], 'Chrome')['window_id'], 2)

    def test_the_refusal_response_carries_candidates_a_hint_and_who_agent(self):
        f = facade(Windows([self.CHROME, self.NOTES]))
        for call in (lambda: f.look(title='Calculator'), lambda: f.do('Press it', title='Calculator', expect=None, control='Go')):
            r = call()
            self.assertEqual((r['status'], r['reason'], r['who']), ('refused', 'window_not_found', 'agent'))
            self.assertEqual({c['title'] for c in r['candidates']}, {'Principal AI Software Engineer', 'Shopping list'})
            self.assertIn('title=<one of candidates[].title>', r.get('hint') or plan.HINTS['window_not_found'])

    def test_a_resolved_app_name_names_the_bound_title(self):
        f = facade(Windows([win(1, 2, 'Demo', 'Google Chrome')]))
        r = f.do('Book the Follow-up slot', title='Chrome', expect=None, records={'fields': {'provider': {'description': 'Provider name'}}}, control='Book')
        self.assertEqual(r['window'], {'title': 'Demo'})


class WhoFixesIt(unittest.TestCase):
    def test_every_catalog_reason_has_a_who(self):
        # MUTATION: a reason in the catalog without a who. Wrong patch: a reason added to HINTS and left out of the table, so its answer says nothing.
        table = plan.who_table()
        catalog = set(plan.HINTS) | set(mobile.DEVICE_HINTS) | set(plan.EXTRA_REASONS)
        self.assertEqual(sorted(catalog - set(table)), [])
        self.assertEqual({table[r] for r in catalog}, {'agent', 'user'})

    def test_the_agent_and_user_reasons_are_split_as_documented(self):
        for reason in ('window_not_found', 'window_ambiguous', 'control_not_found', 'control_ambiguous', 'look_required', 'unknown_look_id', 'records_ambiguous',
                       'select_option_not_offered', 'bad_request', 'delivery_unverified', 'page_changed_since_look', 'tab_not_active'):
            self.assertEqual(plan.who_of(reason), 'agent', reason)
        for reason in ('permission_required', 'foreground_required', 'needs_foreground', 'destructive_control', 'credentials_required', 'login_wall', 'captcha',
                       'agent_browser_misplaced', 'upload_no_file_input', 'window_ax_unresolved', 'pointer_not_deliverable_in_background'):
            self.assertEqual(plan.who_of(reason), 'user', reason)

    def test_a_reason_outside_the_catalog_is_the_users_never_a_retry_on_a_guess(self):
        self.assertEqual(plan.who_of('something_new_nobody_listed'), 'user')

    def test_refused_stopped_failed_and_deferred_answers_carry_who_and_done_ones_do_not(self):
        f = facade(Windows([win(1, 2, 'Demo', 'App')]))
        for status, reason, who in (('refused', 'permission_required', 'user'), ('refused', 'window_ambiguous', 'agent'), ('failed', 'driver_call_failed', 'agent'),
                                    ('deferred', 'confirm_dialog_present', 'agent'), ('stopped', 'destructive_control', 'user')):
            self.assertEqual(f.mark({'status': status, 'reason': reason}, 'do').get('who'), who, reason)
        self.assertNotIn('who', f.mark({'status': 'done'}, 'do'))
        self.assertNotIn('who', f.mark({'status': 'ok'}, 'look'))

    def test_a_plan_answer_takes_who_from_its_failed_steps_reason(self):
        f = facade(Windows([]))
        r = f.mark({'status': 'stopped', 'reason': 'control_not_found', 'steps': [{'n': 1, 'status': 'stopped', 'reason': 'control_not_found'}]}, 'do')
        self.assertEqual(r.get('who'), 'agent')
        r = f.mark({'status': 'stopped', 'steps': [{'n': 1, 'status': 'refused', 'reason': 'login_wall'}]}, 'do')
        self.assertEqual(r.get('who'), 'user')

    def test_a_setup_block_that_needs_the_user_makes_the_answer_the_users(self):
        f = facade(Windows([]))
        r = {'status': 'refused', 'reason': 'perception_not_available', 'setup': [{'check': 'perception', 'status': 'blocker', 'fix': 'install it', 'who': 'user'}]}
        self.assertEqual(f.mark(r, 'look')['who'], 'user')

    def test_the_skill_limits_recovery_to_supported_routes(self):
        from pathlib import Path
        skill=Path(__file__).resolve().parents[1]/'skills/computer-use'
        text=(skill/'SKILL.md').read_text() + (skill/'references/setup.md').read_text()
        for needle in ('who=agent','who=user','context_id','archived routes'):
            self.assertIn(needle,text)


class ForegroundGrantIsPerWindow(unittest.TestCase):
    def setUp(self):
        self.f = facade(Windows([win(1, 2, 'Workday', 'Google Chrome'), win(1, 3, 'Other', 'Google Chrome')]))
        self.f.windows()

    def test_an_approved_window_keeps_its_grant_and_reports_it(self):
        self.assertTrue(self.f.foreground_for(1, 2, explicit=True))
        self.f.foreground_ok = False
        self.assertTrue(self.f.foreground_for(1, 2))
        self.assertEqual(self.f.mark({'status': 'refused', 'reason': 'x'}, 'do')['foreground_granted_for'], ['Workday'])

    def test_the_grant_never_extends_to_another_window(self):
        # MUTATION: the grant leaks to every window (a session-wide flag). Wrong patch: remember "foreground allowed", not which window.
        self.f.foreground_for(1, 2, explicit=True)
        self.f.foreground_ok = False
        self.assertFalse(self.f.foreground_for(1, 3))
        self.assertFalse(self.f.foreground_ok)
        self.assertFalse(self.f.foreground_for(9, 2))

    def test_the_grant_lapses_when_the_windows_title_changes_and_when_the_session_closes(self):
        self.f.foreground_for(1, 2, explicit=True)
        self.f.foreground_ok = False
        self.f.driver.windows[0]['title'] = 'A different page'
        self.f.windows()
        self.assertFalse(self.f.foreground_for(1, 2))
        self.f.driver.windows[0]['title'] = 'Workday'
        self.f.windows()
        self.assertTrue(self.f.foreground_for(1, 2))
        self.f.foreground_ok = False
        self.f.close()
        self.f.windows()
        self.assertFalse(self.f.foreground_for(1, 2))

    def test_no_grant_without_a_listed_title(self):
        self.assertTrue(self.f.foreground_for(7, 8, explicit=True))  # allowed for this call
        self.f.foreground_ok = False
        self.assertFalse(self.f.foreground_for(7, 8))  # but nothing to remember it by


class UnresolvedWindow(unittest.TestCase):
    UNRESOLVED = {'snapshot_id': 's0', 'pid': 1, 'window_id': 2, 'window_title': 'Demo', 'elements': [],
                  'background_input': {'exact_window': {'status': 'ax_unresolved'}, 'routes': [{'route': 'ax', 'status': 'refused', 'reason': 'off_space_or_ax_unresolved'}]}}

    def make(self, unresolved_reads):
        driver = Windows([win(1, 2, 'Demo', 'Google Chrome', is_on_screen=False)])
        base = driver.observe
        left = [unresolved_reads]
        def observe(*args):
            driver.calls.append(('get_window_state', 1))
            if left[0] > 0:
                left[0] -= 1
                return dict(self.UNRESOLVED)
            return base(*args)
        driver.observe = observe
        return driver, facade(driver)

    def test_a_stale_space_view_that_clears_on_the_second_read_proceeds_without_asking(self):
        # Wrong patch: refuse (or ask the user) on the first unresolved answer.
        driver, f = self.make(1)
        try:
            result = f.observe(1, 2)
        except Gap as gap:
            self.fail('refused on the first unresolved answer instead of re-reading: %s' % gap)
        self.assertTrue(result['elements'])
        tools = [t for t, _ in driver.calls]
        self.assertIn('start_session', tools[tools.index('get_window_state'):])
        self.assertGreaterEqual(tools.count('list_windows'), 2)

    def test_still_unresolved_after_the_bounded_rereads_is_window_ax_unresolved_for_the_user_with_the_drivers_evidence(self):
        driver, f = self.make(99)
        r = f.look(title='Demo')
        self.assertEqual((r['status'], r['reason'], r['who']), ('refused', 'window_ax_unresolved', 'user'))
        self.assertIn("'Demo'", r['message'])
        self.assertEqual(r['driver_evidence']['exact_window_status'], 'ax_unresolved')
        self.assertEqual(r['driver_evidence']['refused_routes'], ['off_space_or_ax_unresolved'])
        self.assertIs(r['driver_evidence']['is_on_screen'], False)
        self.assertNotIn('not on screen', r['message'])  # never asserts the user's screen state from a stale listing
        self.assertEqual([t for t, _ in driver.calls].count('get_window_state'), 1 + len(__import__('core').OBSERVE_RETRY_DELAYS))
        self.assertEqual(driver.executed, [])


class TargetByUrl(unittest.TestCase):
    def make(self, tabs, windows=None):
        windows = windows or [win(1, 2, 'Demo', 'Google Chrome'), win(5, 6, 'Agent page', 'Brave Browser'), win(8, 9, 'Shopping list', 'Notes')]
        driver = Windows(windows, tabs)
        return driver, facade(driver)

    def test_exactly_one_matching_tab_binds_its_window_and_the_answer_names_it(self):
        driver, f = self.make({(1, 2): [tab(1, 'https://acme.wd5.myworkday.com/en-US/job/123?x=1', True)], (5, 6): [tab(2, 'https://example.org/', True)]})
        self.assertEqual(pageurl.resolve(f, 'myworkday.com'), {'pid': 1, 'window_id': 2, 'title': 'Demo'})
        r = f.look(url='myworkday.com')
        self.assertEqual((r['status'], r['window']), ('ok', {'title': 'Demo'}))

    def test_the_agent_browser_is_searched_like_the_users_windows(self):
        driver, f = self.make({(1, 2): [tab(1, 'https://example.org/', True)], (5, 6): [tab(2, 'https://clinic.example/book', True)]})
        self.assertEqual(pageurl.resolve(f, 'clinic.example')['window_id'], 6)

    def test_several_matching_tabs_are_ambiguous_with_titles_and_urls_and_never_the_first(self):
        # MUTATION: bind the first of several matching tabs. Wrong patch: take matches[0].
        driver, f = self.make({(1, 2): [tab(1, 'https://a.myworkday.com/home?token=SECRET', True)], (5, 6): [tab(2, 'https://b.myworkday.com/job', True)]})
        with self.assertRaises(WindowRefusal) as caught:
            pageurl.resolve(f, 'myworkday.com')
        error = caught.exception
        self.assertEqual(error.reason, 'window_ambiguous')
        self.assertEqual([(c['title'], c['url']) for c in error.candidates], [('Demo', 'a.myworkday.com/home'), ('Agent page', 'b.myworkday.com/job')])
        self.assertNotIn('SECRET', str(error.candidates) + str(error))

    def test_two_matching_tabs_of_one_window_are_ambiguous_too(self):
        driver, f = self.make({(1, 2): [tab(1, 'https://a.myworkday.com/x', True), tab(2, 'https://a.myworkday.com/y')]})
        with self.assertRaises(WindowRefusal) as caught:
            pageurl.resolve(f, 'myworkday')
        self.assertEqual((caught.exception.reason, len(caught.exception.candidates)), ('window_ambiguous', 2))

    def test_no_match_lists_the_open_pages_by_domain_only_at_most_eight(self):
        tabs = [tab(i, 'https://site%d.example/private/path?q=secret' % i, i == 0) for i in range(12)]
        driver, f = self.make({(1, 2): tabs})
        with self.assertRaises(WindowRefusal) as caught:
            pageurl.resolve(f, 'myworkday.com')
        error = caught.exception
        self.assertEqual((error.reason, len(error.candidates)), ('window_not_found', 8))
        self.assertTrue(all(c['url'].endswith('.example') and '/' not in c['url'] for c in error.candidates))
        self.assertNotIn('secret', str(error))

    def test_a_match_in_a_background_tab_is_refused_for_the_agent_and_nothing_is_switched(self):
        driver, f = self.make({(1, 2): [tab(1, 'https://example.org/', True), tab(2, 'https://a.myworkday.com/job')]})
        r = f.look(url='myworkday.com')
        self.assertEqual((r['status'], r['reason'], r['who']), ('refused', 'tab_not_active', 'agent'))
        self.assertEqual(r['candidates'][0]['title'], 'Demo')
        self.assertEqual([t for t, _ in driver.calls if t not in ('list_windows', 'get_browser_state', 'start_session')], [])

    def test_only_browser_windows_are_asked_for_tabs(self):
        driver, f = self.make({(1, 2): [tab(1, 'https://a.myworkday.com/job', True)]})
        pageurl.resolve(f, 'myworkday.com')
        self.assertNotIn(8, [pid for tool, pid in driver.calls if tool == 'get_browser_state'])

    def test_a_window_the_driver_will_not_attach_to_is_skipped_but_all_refused_is_permission_required(self):
        driver, f = self.make({(1, 2): [tab(1, 'https://a.myworkday.com/job', True)]})
        self.assertEqual(pageurl.resolve(f, 'myworkday.com')['window_id'], 2)  # the agent browser window (5,6) had no state and is skipped
        driver, f = self.make({})
        with self.assertRaises(Gap) as caught:
            pageurl.resolve(f, 'myworkday.com')
        self.assertIn('browser_not_prepared', str(caught.exception))

    def test_url_with_another_target_or_a_too_short_needle_is_a_bad_request(self):
        driver, f = self.make({(1, 2): [tab(1, 'https://a.myworkday.com/job', True)]})
        self.assertEqual(f.look(url='myworkday.com', title='Demo')['reason'], 'bad_request')
        self.assertEqual(f.look(url='my')['reason'], 'bad_request')
        self.assertEqual(f.look(url='myworkday.com', device='x')['reason'], 'bad_request')


class OnBehalfMode(unittest.TestCase):
    def test_mode_grants_foreground_to_the_resolved_user_window_without_a_per_step_flag(self):
        driver = Windows([win(1, 2, 'Workday application', 'Google Chrome')])
        f = Facade(driver, generic_factory=FakeChooser, reader_factory=FakeReader, visual_factory=FakeVision, on_behalf=True, foreground_on_behalf=True)
        target = f.resolve_window('Google Chrome')
        self.assertEqual((target['pid'], target['window_id']), (1, 2))
        self.assertTrue(f.foreground_for(1, 2))
        self.assertTrue(f.foreground_ok)

    def test_a_titleless_first_navigation_is_only_enabled_in_on_behalf_mode(self):
        steps = [{'do': 'goto', 'url': 'https://workday.example/jobs', 'expect': None}]
        f = facade(Windows([win(1, 2, 'Workday application', 'Google Chrome')]))
        self.assertFalse(plan.starts_on_user_browser(f, steps))
        f.on_behalf = True
        self.assertTrue(plan.starts_on_user_browser(f, steps))
        normalized = plan.validate(f, 'Open my job application', None, None, None, steps, None, None, 20, None, {})
        self.assertEqual(normalized[0]['do'], 'goto')

    def test_user_browser_is_the_default_browser_route_in_on_behalf_mode(self):
        driver = Windows([win(1, 2, 'Workday application', 'Google Chrome')])
        f = Facade(driver, generic_factory=FakeChooser, reader_factory=FakeReader, visual_factory=FakeVision, agent_browser=type('Browser', (), {'mode': 'auto'})(), on_behalf=True)
        ctx = {'pid': None, 'window_id': None}
        plan.resolve_browser_window(f, {'do': 'goto'}, ctx, None)
        self.assertEqual((ctx['pid'], ctx['window_id']), (1, 2))

    def test_visible_mode_uses_verified_fronting_and_foreground_driver_delivery(self):
        class FocusDriver(Windows):
            def call(self, tool, args, timeout=20):
                if tool == 'bring_to_front':
                    self.calls.append((tool, args.get('pid')))
                    return {'effect':'confirmed'}
                return super().call(tool, args, timeout)
        driver = FocusDriver([win(1, 2, 'Workday application', 'Google Chrome')])
        f = facade(driver);f.on_behalf=True;f.foreground_on_behalf=True
        state = f.state(f.observe(1, 2)['snapshot'])
        action = f.actions(state, ['e3'], 'click', None)[0]
        self.assertEqual(action['arguments']['delivery_mode'], 'foreground')
        self.assertEqual(f.front_window(1, 2)['effect'], 'confirmed')
        self.assertIn(('bring_to_front', 1), driver.calls)

    def test_background_mode_keeps_actions_on_the_driver_background_route(self):
        driver = Windows([win(1, 2, 'Workday application', 'Google Chrome')])
        f = facade(driver);f.on_behalf=True
        state = f.state(f.observe(1, 2)['snapshot'])
        action = f.actions(state, ['e3'], 'click', None)[0]
        self.assertNotIn('delivery_mode', action['arguments'])
        self.assertFalse(f.foreground_for(1, 2))


if __name__ == '__main__':
    unittest.main()
